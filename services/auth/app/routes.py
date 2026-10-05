import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.deps import get_current_user
from common.errors import AppError, ServiceUnavailableError
from common.rate_limit import SlidingWindowRateLimiter
from common.responses import success_response
from common.security import AuthUser

from app.models import User
from app.settings import AuthSettings
from app.tokens import issue_token_pair, revoke_by_raw_token, rotate_refresh_token, serialize_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

request_otp_limiter = SlidingWindowRateLimiter("auth_request_otp", limit=3, window_seconds=60)
verify_otp_limiter = SlidingWindowRateLimiter("auth_verify_otp", limit=5, window_seconds=60)
refresh_limiter = SlidingWindowRateLimiter("auth_refresh", limit=20, window_seconds=60)


class RequestOtpBody(BaseModel):
    email: EmailStr


class VerifyOtpBody(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


async def get_or_create_user(session: AsyncSession, email: str, settings: AuthSettings) -> User:
    should_be_admin = email in settings.admin_email_set
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(id=str(uuid4()), email=email, role="admin" if should_be_admin else "member")
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()
    elif should_be_admin and user.role != "admin":
        user.role = "admin"

    user.last_login_at = datetime.now(timezone.utc)
    return user


@router.post("/request-otp", dependencies=[Depends(request_otp_limiter)])
async def request_otp(body: RequestOtpBody, request: Request):
    settings: AuthSettings = request.app.state.settings
    email = body.email.lower()
    otp_service = request.app.state.otp
    code = await otp_service.issue(email)
    try:
        await request.app.state.mailer.send_otp(email, code)
    except AppError:
        await otp_service.discard(email)
        raise
    except Exception:
        logger.exception("Failed to send OTP email")
        await otp_service.discard(email)
        raise ServiceUnavailableError("Could not send the email, try again shortly") from None
    return success_response({"sent": True, "expires_in": settings.otp_ttl_seconds}, "Code sent")


@router.post("/verify-otp", dependencies=[Depends(verify_otp_limiter)])
async def verify_otp(body: VerifyOtpBody, request: Request, session: AsyncSession = Depends(get_session)):
    settings: AuthSettings = request.app.state.settings
    email = body.email.lower()
    await request.app.state.otp.verify(email, body.code)
    user = await get_or_create_user(session, email, settings)
    pair = await issue_token_pair(session, settings, user)
    await session.commit()
    return success_response(pair, "Signed in")


@router.post("/refresh", dependencies=[Depends(refresh_limiter)])
async def refresh(body: RefreshBody, request: Request, session: AsyncSession = Depends(get_session)):
    pair = await rotate_refresh_token(session, request.app.state.settings, body.refresh_token)
    await session.commit()
    return success_response(pair, "Token refreshed")


@router.post("/logout", dependencies=[Depends(refresh_limiter)])
async def logout(body: RefreshBody, session: AsyncSession = Depends(get_session)):
    await revoke_by_raw_token(session, body.refresh_token)
    await session.commit()
    return success_response(None, "Signed out")


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    stored = await session.get(User, user.id)
    return success_response(serialize_user(stored) if stored else {"id": user.id, "email": user.email, "role": user.role})
