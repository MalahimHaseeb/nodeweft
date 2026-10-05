import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import UnauthorizedError
from common.security import create_access_token

from app.models import RefreshToken, User
from app.settings import AuthSettings


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def serialize_user(user: User) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role}


async def issue_token_pair(
    session: AsyncSession,
    settings: AuthSettings,
    user: User,
    family_id: str | None = None,
) -> dict:
    raw_refresh = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            id=str(uuid4()),
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            family_id=family_id or str(uuid4()),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        )
    )
    return {
        "access_token": create_access_token(settings, user.id, user.email, user.role),
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "user": serialize_user(user),
    }


async def revoke_family(session: AsyncSession, family_id: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def rotate_refresh_token(session: AsyncSession, settings: AuthSettings, raw_token: str) -> dict:
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update()
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise UnauthorizedError("Invalid refresh token")

    now = datetime.now(timezone.utc)
    if stored.revoked_at is not None:
        await revoke_family(session, stored.family_id)
        await session.commit()
        raise UnauthorizedError("Refresh token was already used")
    if stored.expires_at <= now:
        raise UnauthorizedError("Refresh token expired")

    user = await session.get(User, stored.user_id)
    if user is None:
        raise UnauthorizedError("Invalid refresh token")

    stored.revoked_at = now
    return await issue_token_pair(session, settings, user, family_id=stored.family_id)


async def revoke_by_raw_token(session: AsyncSession, raw_token: str) -> None:
    result = await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    stored = result.scalar_one_or_none()
    if stored is not None:
        await revoke_family(session, stored.family_id)
