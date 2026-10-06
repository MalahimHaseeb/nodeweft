from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.deps import get_current_user, require_admin
from common.security import AuthUser
from common.errors import register_error_handlers

from app.mailer import EmailSender
from app.settings import AuthSettings

from app.models import User
from app.routes import get_session, router


class _Result:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user

    def scalar_one(self):
        if self._user is None:
            raise AssertionError("Expected user")
        return self._user


class FakeSession:
    def __init__(self, existing_user=None):
        self._existing_user = existing_user
        self.added = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, _statement):
        return _Result(self._existing_user)

    def add(self, user):
        self.added.append(user)
        self._existing_user = user

    async def flush(self):
        self.flush_calls += 1

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1


class FakeMailer:
    def __init__(self):
        self.invites = []

    async def send_invite(self, recipient, invited_by):
        self.invites.append((recipient, invited_by))


def make_client(session: FakeSession, mailer: FakeMailer, *, as_admin: bool = True) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)  
    app.include_router(router)
    app.state.mailer = mailer

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session

    if as_admin:
        async def override_require_admin():
            return AuthUser(id="admin-1", email="admin@example.com", role="admin")

        app.dependency_overrides[require_admin] = override_require_admin
    else:
        async def override_current_user():
            return AuthUser(id="member-1", email="member@example.com", role="member")

        app.dependency_overrides[get_current_user] = override_current_user

    return TestClient(app)


def test_invite_creates_member_and_sends_email():
    session = FakeSession()
    mailer = FakeMailer()

    with make_client(session, mailer, as_admin=True) as client:
        response = client.post("/auth/users/invite", json={"email": "new.user@example.com"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["created"] is True
    assert payload["data"]["user"]["email"] == "new.user@example.com"
    assert payload["data"]["user"]["role"] == "member"
    assert session.commit_calls == 1
    assert len(session.added) == 1
    assert mailer.invites == [("new.user@example.com", "admin@example.com")]


def test_invite_existing_user_resends_email_without_recreate():
    existing = User(id="u-1", email="existing@example.com", role="member")
    session = FakeSession(existing_user=existing)
    mailer = FakeMailer()

    with make_client(session, mailer, as_admin=True) as client:
        response = client.post("/auth/users/invite", json={"email": "existing@example.com"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["data"]["created"] is False
    assert session.commit_calls == 0
    assert len(session.added) == 0
    assert mailer.invites == [("existing@example.com", "admin@example.com")]


def test_invite_requires_admin_role():
    session = FakeSession()
    mailer = FakeMailer()

    with make_client(session, mailer, as_admin=False) as client:
        response = client.post("/auth/users/invite", json={"email": "member.only@example.com"})

    assert response.status_code == 403


async def test_send_invite_matches_send_signature():
    sender = EmailSender(AuthSettings(app_env="development", smtp_host=""))
    await sender.send_invite("a@example.com", "admin@example.com")