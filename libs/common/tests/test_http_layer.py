
from fastapi import Depends
from fastapi.testclient import TestClient

from common.app import create_service_app
from common.config import CommonSettings
from common.errors import NotFoundError
from common.rate_limit import SlidingWindowRateLimiter
from common.responses import success_response


class FakeRedis:
    def __init__(self):
        self.counters = {}

    async def eval(self, script, numkeys, current_key, previous_key, window_seconds):
        self.counters[current_key] = self.counters.get(current_key, 0) + 1
        return [self.counters[current_key], self.counters.get(previous_key, 0)]

    async def aclose(self):
        return None


def build_app():
    app = create_service_app("test", CommonSettings())
    app.state.redis = FakeRedis()
    limiter = SlidingWindowRateLimiter("probe", limit=2, window_seconds=60)

    @app.get("/limited", dependencies=[Depends(limiter)])
    async def limited():
        return success_response({"ok": True})

    @app.get("/missing")
    async def missing():
        raise NotFoundError("Thing")

    return app


def test_envelope_on_success_and_error():
    client = TestClient(build_app())
    ok = client.get("/health").json()
    assert ok["success"] is True and ok["error"] is None
    missing = client.get("/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_rate_limit_returns_429_with_retry_after():
    client = TestClient(build_app())
    headers = {"x-forwarded-for": "9.9.9.9"}
    assert client.get("/limited", headers=headers).status_code == 200
    assert client.get("/limited", headers=headers).status_code == 200
    blocked = client.get("/limited", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_spoofed_forwarded_for_prefix_does_not_bypass_limit():
    client = TestClient(build_app())
    statuses = [
        client.get("/limited", headers={"x-forwarded-for": f"{index}.1.1.1, 9.9.9.9"}).status_code
        for index in range(4)
    ]
    assert statuses == [200, 200, 429, 429]


def test_oversized_body_rejected():
    client = TestClient(build_app())
    response = client.post("/missing", content=b"x", headers={"content-length": "999999999"})
    assert response.status_code == 413
