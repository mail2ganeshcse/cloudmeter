from datetime import UTC, datetime
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, get_db
from app.main import app
from app.models import UserAccount, UserSession
from app.settings import settings


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session, monkeypatch):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    startup_handlers = app.router.on_startup
    app.router.on_startup = []
    with TestClient(app) as test_client:
        yield test_client
    app.router.on_startup = startup_handlers
    app.dependency_overrides.clear()


def google_claims(email="user@gmail.com", sub="google-sub-1", verified=True):
    return {
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "name": "Cloud User",
        "picture": "https://example.com/avatar.png",
        "hd": email.split("@")[-1],
        "iat": int(datetime.now(UTC).timestamp()),
    }


def test_google_login_creates_user_session_and_cookie(client, db_session, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims())

    response = client.post("/api/auth/google", json={"credential": "header.payload.signature"})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "user@gmail.com"
    assert body["user"]["hasPassword"] is False
    assert body["session"]["role"] == "viewer"
    assert response.cookies.get(settings.session_cookie_name)
    assert db_session.query(UserAccount).count() == 1
    assert db_session.query(UserSession).count() == 1
    assert db_session.query(UserSession).first().token_hash != body["session"]["accessToken"]


def test_google_login_updates_returning_user(client, db_session, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="first@gmail.com"))
    first = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert first.status_code == 200

    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="second@gmail.com"))
    second = client.post("/api/auth/google", json={"credential": "header.payload.signature"})

    assert second.status_code == 200
    assert db_session.query(UserAccount).count() == 1
    assert db_session.query(UserAccount).first().email == "second@gmail.com"
    assert db_session.query(UserSession).count() == 2


def test_google_login_rejects_missing_credential(client):
    response = client.post("/api/auth/google", json={})

    assert response.status_code == 422


def test_google_login_rejects_invalid_token(client, monkeypatch):
    def fail_verify(*args):
        raise ValueError("bad token")

    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", fail_verify)

    response = client.post("/api/auth/google", json={"credential": "bad-token"})

    assert response.status_code == 401


def test_google_login_rejects_unverified_email(client, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(verified=False))

    response = client.post("/api/auth/google", json={"credential": "valid-token"})

    assert response.status_code == 401


def test_auth_me_and_logout(client, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="admin@example.com"))
    login = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert login.status_code == 200

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["session"]["role"] == "admin"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    after_logout = client.get("/api/auth/me")
    assert after_logout.status_code == 401


def test_google_login_can_bind_local_password(client, db_session, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="linked@gmail.com"))

    response = client.post(
        "/api/auth/google",
        json={"credential": "header.payload.signature", "username": "linked@gmail.com", "password": "cloudmeter123"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["hasPassword"] is True
    account = db_session.query(UserAccount).filter(UserAccount.email == "linked@gmail.com").first()
    assert account.password_hash
    assert account.password_hash != "cloudmeter123"


def test_password_login_uses_saved_local_credentials(client, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="local@gmail.com"))
    google = client.post(
        "/api/auth/google",
        json={"credential": "header.payload.signature", "username": "local@gmail.com", "password": "cloudmeter123"},
    )
    assert google.status_code == 200
    client.post("/api/auth/logout")

    login = client.post("/api/auth/login", json={"username": "local@gmail.com", "password": "cloudmeter123"})

    assert login.status_code == 200
    assert login.json()["user"]["email"] == "local@gmail.com"


def test_password_login_rejects_bad_password(client, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="badpass@gmail.com"))
    google = client.post(
        "/api/auth/google",
        json={"credential": "header.payload.signature", "username": "badpass@gmail.com", "password": "cloudmeter123"},
    )
    assert google.status_code == 200
    client.post("/api/auth/logout")

    login = client.post("/api/auth/login", json={"username": "badpass@gmail.com", "password": "wrong-password"})

    assert login.status_code == 401
