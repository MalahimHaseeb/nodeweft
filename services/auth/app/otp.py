import hashlib
import hmac
import secrets

from redis.asyncio import Redis

from common.errors import AppError, BadRequestError, RateLimitExceeded, UnauthorizedError
from common.security import secrets_match

from app.settings import AuthSettings


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class OtpService:
    def __init__(self, redis: Redis, settings: AuthSettings):
        self._redis = redis
        self._settings = settings

    def _digest(self, email: str, code: str) -> str:
        return hmac.new(
            self._settings.otp_secret.encode(),
            f"{email}:{code}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _keys(self, email: str) -> dict[str, str]:
        return {
            "code": f"otp:code:{email}",
            "attempts": f"otp:attempts:{email}",
            "cooldown": f"otp:cooldown:{email}",
            "hourly": f"otp:hourly:{email}",
        }

    async def issue(self, email: str) -> str:
        keys = self._keys(email)
        acquired = await self._redis.set(
            keys["cooldown"], "1", ex=self._settings.otp_resend_cooldown_seconds, nx=True
        )
        if not acquired:
            remaining = await self._redis.ttl(keys["cooldown"])
            raise RateLimitExceeded(remaining if remaining > 0 else 1, "Please wait before requesting another code")

        sent_this_hour = await self._redis.incr(keys["hourly"])
        if sent_this_hour == 1:
            await self._redis.expire(keys["hourly"], 3600)
        if sent_this_hour > self._settings.otp_hourly_limit:
            remaining = await self._redis.ttl(keys["hourly"])
            raise RateLimitExceeded(remaining if remaining > 0 else 3600, "Too many codes requested for this email")

        code = generate_code()
        await self._redis.set(keys["code"], self._digest(email, code), ex=self._settings.otp_ttl_seconds)
        await self._redis.delete(keys["attempts"])
        return code

    async def discard(self, email: str) -> None:
        keys = self._keys(email)
        await self._redis.delete(keys["code"], keys["attempts"], keys["cooldown"])

    async def verify(self, email: str, code: str) -> None:
        keys = self._keys(email)
        stored = await self._redis.get(keys["code"])
        if stored is None:
            raise BadRequestError("Code expired or was never requested")

        attempts = await self._redis.incr(keys["attempts"])
        if attempts == 1:
            await self._redis.expire(keys["attempts"], self._settings.otp_ttl_seconds)
        if attempts > self._settings.otp_max_attempts:
            await self._redis.delete(keys["code"], keys["attempts"])
            raise AppError("OTP_ATTEMPTS_EXCEEDED", "Too many wrong attempts, request a new code", 429)

        if not secrets_match(stored, self._digest(email, code)):
            raise UnauthorizedError("Invalid code")

        consumed = await self._redis.delete(keys["code"])
        await self._redis.delete(keys["attempts"])
        if consumed == 0:
            raise UnauthorizedError("Code already used")
