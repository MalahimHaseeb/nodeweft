from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from common.errors import ForbiddenError, UnauthorizedError
from common.security import AuthUser, decode_access_token, secrets_match

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AuthUser:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise UnauthorizedError()
    user = decode_access_token(request.app.state.settings, credentials.credentials)
    request.state.user_id = user.id
    return user


async def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user


async def require_internal_token(request: Request) -> None:
    provided = request.headers.get("x-internal-token", "")
    expected = request.app.state.settings.internal_service_token
    if not provided or not secrets_match(provided, expected):
        raise UnauthorizedError("Invalid service token")
