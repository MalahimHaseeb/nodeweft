import hmac
import time
from dataclasses import dataclass

import jwt

from common.config import CommonSettings
from common.errors import UnauthorizedError


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def create_access_token(settings: CommonSettings, user_id: str, email: str, role: str) -> str:
    issued_at = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iss": settings.jwt_issuer,
        "iat": issued_at,
        "exp": issued_at + settings.access_token_minutes * 60,
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(settings: CommonSettings, token: str) -> AuthUser:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token expired") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid token") from None
    if payload.get("typ") != "access":
        raise UnauthorizedError("Invalid token")
    return AuthUser(
        id=str(payload["sub"]),
        email=str(payload.get("email", "")),
        role=str(payload.get("role", "member")),
    )


def secrets_match(first: str, second: str) -> bool:
    return hmac.compare_digest(first.encode(), second.encode())
