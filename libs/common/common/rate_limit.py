import math
import time
from typing import Optional

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from common.errors import RateLimitExceeded

WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]) * 2)
end
local previous = tonumber(redis.call('GET', KEYS[2]) or '0')
return {current, previous}
"""


def resolve_client_identity(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    settings = getattr(request.app.state, "settings", None)
    trusted_hops = getattr(settings, "trusted_proxy_hops", 1)
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    if trusted_hops >= 1 and len(hops) >= trusted_hops:
        return f"ip:{hops[-trusted_hops]}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


class SlidingWindowRateLimiter:
    def __init__(self, scope: str, limit: int, window_seconds: int):
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        self.scope = scope
        self.limit = limit
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        redis_client: Optional[Redis] = getattr(request.app.state, "redis", None)
        if redis_client is None:
            return

        now = time.time()
        window_index = int(now // self.window_seconds)
        elapsed_in_window = now - window_index * self.window_seconds
        identity = resolve_client_identity(request)
        current_key = f"rl:{self.scope}:{identity}:{window_index}"
        previous_key = f"rl:{self.scope}:{identity}:{window_index - 1}"

        try:
            current_count, previous_count = await redis_client.eval(
                WINDOW_SCRIPT, 2, current_key, previous_key, self.window_seconds
            )
        except RedisError:
            return

        previous_weight = 1 - elapsed_in_window / self.window_seconds
        estimated_requests = int(previous_count) * previous_weight + int(current_count)

        if estimated_requests > self.limit:
            raise RateLimitExceeded(math.ceil(self.window_seconds - elapsed_in_window))
