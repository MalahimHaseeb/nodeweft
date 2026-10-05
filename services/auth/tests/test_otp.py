import pytest

from common.errors import AppError, BadRequestError, RateLimitExceeded, UnauthorizedError

from app.otp import OtpService, generate_code
from app.settings import AuthSettings


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        self.ttls[key] = ex
        return True

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    async def expire(self, key, seconds):
        self.ttls[key] = seconds

    async def ttl(self, key):
        return self.ttls.get(key) or 30

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed


@pytest.fixture
def service():
    return OtpService(FakeRedis(), AuthSettings())


def different_code(code):
    return "000001" if code == "000000" else "000000"


def test_generate_code_is_six_digits():
    for _ in range(50):
        code = generate_code()
        assert len(code) == 6 and code.isdigit()


async def test_issue_then_verify_succeeds_once(service):
    code = await service.issue("a@x.com")
    await service.verify("a@x.com", code)
    with pytest.raises(BadRequestError):
        await service.verify("a@x.com", code)


async def test_wrong_code_rejected(service):
    code = await service.issue("a@x.com")
    with pytest.raises(UnauthorizedError):
        await service.verify("a@x.com", different_code(code))


async def test_attempts_exhausted(service):
    code = await service.issue("a@x.com")
    wrong = "123456" if code != "123456" else "654321"
    for _ in range(5):
        with pytest.raises(UnauthorizedError):
            await service.verify("a@x.com", wrong)
    with pytest.raises(AppError) as blocked:
        await service.verify("a@x.com", code)
    assert blocked.value.status_code == 429


async def test_resend_cooldown(service):
    await service.issue("a@x.com")
    with pytest.raises(RateLimitExceeded):
        await service.issue("a@x.com")


async def test_code_bound_to_email(service):
    code_for_a = await service.issue("a@x.com")
    code_for_b = await service.issue("b@x.com")
    if code_for_a == code_for_b:
        return
    with pytest.raises(UnauthorizedError):
        await service.verify("b@x.com", code_for_a)
