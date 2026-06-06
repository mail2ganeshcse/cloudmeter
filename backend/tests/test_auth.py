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
from app.models import ClusterConnection, Customer, KubernetesCost, NetworkUsage, UserAccount, UserSession
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


def test_superadmin_can_change_user_role_and_role_persists(client, db_session, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="user@gmail.com", sub="viewer-sub"))
    viewer_login = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert viewer_login.status_code == 200
    viewer = db_session.query(UserAccount).filter(UserAccount.email == "user@gmail.com").first()
    assert viewer.role == "viewer"
    client.post("/api/auth/logout")

    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="raashviroyal@gmail.com", sub="master-sub"))
    admin_login = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert admin_login.status_code == 200
    assert admin_login.json()["session"]["role"] == "superadmin"

    response = client.patch(f"/api/users/{viewer.id}/role", json={"role": "superadmin"})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "superadmin"
    db_session.refresh(viewer)
    assert viewer.role == "superadmin"
    client.post("/api/auth/logout")

    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="user@gmail.com", sub="viewer-sub"))
    returning_login = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert returning_login.status_code == 200
    assert returning_login.json()["session"]["role"] == "superadmin"


def test_viewer_cannot_change_roles_and_master_cannot_be_demoted(client, db_session, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="user@gmail.com", sub="viewer-sub"))
    viewer_login = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert viewer_login.status_code == 200
    viewer = db_session.query(UserAccount).filter(UserAccount.email == "user@gmail.com").first()
    response = client.patch(f"/api/users/{viewer.id}/role", json={"role": "admin"})
    assert response.status_code == 403
    client.post("/api/auth/logout")

    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="raashviroyal@gmail.com", sub="master-sub"))
    admin_login = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert admin_login.status_code == 200
    master = db_session.query(UserAccount).filter(UserAccount.email == "raashviroyal@gmail.com").first()
    response = client.patch(f"/api/users/{master.id}/role", json={"role": "viewer"})
    assert response.status_code == 400
    db_session.refresh(master)
    assert master.role == "superadmin"


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


def test_authenticated_user_can_set_local_password(client, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="setpass@gmail.com"))
    google = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert google.status_code == 200
    assert google.json()["user"]["hasPassword"] is False

    set_password = client.post("/api/auth/password", json={"password": "cloudmeter123"})
    assert set_password.status_code == 200
    assert set_password.json()["user"]["hasPassword"] is True
    client.post("/api/auth/logout")

    login = client.post("/api/auth/login", json={"username": "setpass@gmail.com", "password": "cloudmeter123"})
    assert login.status_code == 200


def test_authenticated_user_can_save_profile_and_complete_onboarding(client, db_session, monkeypatch):
    monkeypatch.setattr("app.main.id_token.verify_oauth2_token", lambda *args: google_claims(email="profile@gmail.com"))
    google = client.post("/api/auth/google", json={"credential": "header.payload.signature"})
    assert google.status_code == 200
    assert google.json()["user"]["onboardingComplete"] is False

    profile = client.post(
        "/api/auth/profile",
        json={"first_name": "John", "last_name": "Smith", "country_code": "+91", "phone_number": "9876543210"},
    )
    assert profile.status_code == 200
    assert profile.json()["user"]["firstName"] == "John"
    assert profile.json()["user"]["lastName"] == "Smith"
    assert profile.json()["user"]["phoneNumber"] == "9876543210"

    complete = client.post("/api/auth/onboarding/complete")
    assert complete.status_code == 200
    assert complete.json()["user"]["onboardingComplete"] is True

    account = db_session.query(UserAccount).filter(UserAccount.email == "profile@gmail.com").first()
    assert account.name == "John Smith"
    assert account.onboarding_complete is True


class FakeOAuthResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        return None


def test_github_oauth_callback_creates_session(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "github_client_id", "github-client")
    monkeypatch.setattr(settings, "github_client_secret", "github-secret")
    monkeypatch.setattr(settings, "public_api_url", "https://cloudmeter.test")
    monkeypatch.setattr(settings, "frontend_url", "https://app.cloudmeter.test")

    def fake_post(*args, **kwargs):
        return FakeOAuthResponse({"access_token": "gh-token"})

    def fake_get(url, *args, **kwargs):
        if url.endswith("/user"):
            return FakeOAuthResponse({"id": 42, "login": "octo", "name": "Octo User", "avatar_url": "https://example.com/octo.png"})
        return FakeOAuthResponse([{"email": "octo@example.com", "primary": True, "verified": True}])

    monkeypatch.setattr("app.main.requests.post", fake_post)
    monkeypatch.setattr("app.main.requests.get", fake_get)

    client.cookies.set("cloudmeter_github_state", "state-1")
    response = client.get("/api/auth/github/callback?code=abc&state=state-1", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://app.cloudmeter.test"
    assert response.cookies.get(settings.session_cookie_name)
    account = db_session.query(UserAccount).filter(UserAccount.email == "octo@example.com").first()
    assert account.provider == "github"
    assert account.github_sub == "42"


def test_sso_oauth_callback_creates_session(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "sso_client_id", "sso-client")
    monkeypatch.setattr(settings, "sso_client_secret", "sso-secret")
    monkeypatch.setattr(settings, "sso_token_url", "https://idp.example.com/token")
    monkeypatch.setattr(settings, "sso_userinfo_url", "https://idp.example.com/userinfo")
    monkeypatch.setattr(settings, "public_api_url", "https://cloudmeter.test")
    monkeypatch.setattr(settings, "frontend_url", "https://app.cloudmeter.test")

    monkeypatch.setattr("app.main.requests.post", lambda *args, **kwargs: FakeOAuthResponse({"access_token": "sso-token"}))
    monkeypatch.setattr(
        "app.main.requests.get",
        lambda *args, **kwargs: FakeOAuthResponse({"sub": "sso-sub-1", "email": "sso@example.com", "email_verified": True, "name": "SSO User"}),
    )

    client.cookies.set("cloudmeter_sso_state", "state-2")
    response = client.get("/api/auth/sso/callback?code=abc&state=state-2", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://app.cloudmeter.test"
    assert response.cookies.get(settings.session_cookie_name)
    account = db_session.query(UserAccount).filter(UserAccount.email == "sso@example.com").first()
    assert account.provider == "sso"
    assert account.sso_sub == "sso-sub-1"


def test_agent_install_script_uses_valid_shell_json(client):
    response = client.get("/api/agent/install.sh")

    assert response.status_code == 200
    script = response.text
    assert '-d \'{"token":"\'"${CLOUDMETER_TOKEN}"\'"' in script
    assert '"cluster_name":"\'"${CLOUDMETER_CLUSTER}"\'"' in script
    assert 'AGENT_NAME="cloudmeter-agent-${CLUSTER_SLUG}"' in script
    assert "cat <<'EOF' | sed" in script
    assert "app.kubernetes.io/instance: __CLUSTER_SLUG__" in script
    assert 'value="$1"' in script
    assert "printf '%s\\n' \"$metrics\"" in script
    assert "printf '%s\\n' \"$pod_counts\"" in script
    assert "printf '%s\n' \"$metrics\"" not in script
    assert '\\"pods\\":[${pods_json}]' in script
    assert "/api/agent/snapshot" in script
    assert 'NETWORK_AGENT_NAME="cloudmeter-network-agent-${CLUSTER_SLUG}"' in script
    assert "__NETWORK_AGENT_NAME__" in script
    assert 'resources: ["nodes/proxy"]' in script
    assert "/proxy/stats/summary" in script
    assert "kubelet-summary" in script
    assert "kubectl rollout status -n cloudmeter-agent" in script
    assert "/api/agent/network" in script
    assert "CLOUDMETER_PROMETHEUS_URL" in script


def test_agent_snapshot_replaces_cluster_demo_rows(client, db_session):
    customer = Customer(name="Snapshot Co", segment="SaaS", region="India", billing_model="K8s")
    db_session.add(customer)
    db_session.flush()
    db_session.add(
        ClusterConnection(
            customer_id=customer.id,
            cluster_name="real-cluster",
            provider="Anywhere",
            environment="Production",
            token="cm_real_cluster",
            status="pending",
        )
    )
    db_session.add(
        KubernetesCost(
            customer_id=customer.id,
            cluster="real-cluster",
            namespace="demo",
            workload="old-demo",
            team="Demo",
            cpu_core_hours=999,
            memory_gb_hours=999,
            gpu_hours=0,
            amount_inr=999,
            month="2026-06",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/agent/snapshot",
        json={
            "token": "cm_real_cluster",
            "cluster_name": "real-cluster",
            "provider": "Anywhere",
            "node_count": 2,
            "pod_count": 3,
            "namespaces": [
                {"namespace": "payments", "pods": 2, "cpu_millicores": 250, "memory_mib": 512},
                {"namespace": "qa", "pods": 1, "cpu_millicores": 50, "memory_mib": 128},
            ],
            "pods": [
                {"namespace": "payments", "pod": "api-1", "cpu_millicores": 200, "memory_mib": 256},
                {"namespace": "payments", "pod": "worker-1", "cpu_millicores": 50, "memory_mib": 128},
                {"namespace": "qa", "pod": "runner-1", "cpu_millicores": 25, "memory_mib": 64},
            ],
        },
    )

    assert response.status_code == 200
    rows = db_session.query(KubernetesCost).filter(KubernetesCost.cluster == "real-cluster").order_by(KubernetesCost.namespace, KubernetesCost.workload).all()
    assert [row.workload for row in rows] == ["pod/api-1", "pod/worker-1", "pod/runner-1"]
    assert rows[0].cpu_core_hours == 0.2
    assert rows[0].memory_gb_hours == 0.25

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    real_rows = [row for row in dashboard.json()["kubernetes"] if row["cluster"] == "real-cluster"]
    assert real_rows[0]["source"] == "live"
    assert all(row["workload"].startswith("pod/") for row in real_rows)


def test_agent_network_ingestion_updates_dashboard(client, db_session):
    customer = Customer(name="Network Co", segment="SaaS", region="India", billing_model="Network")
    db_session.add(customer)
    db_session.flush()
    db_session.add(
        ClusterConnection(
            customer_id=customer.id,
            cluster_name="network-cluster",
            provider="Anywhere",
            environment="Production",
            token="cm_network_cluster",
            status="connected",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/agent/network",
        json={
            "token": "cm_network_cluster",
            "cluster_name": "network-cluster",
            "provider": "Anywhere",
            "metrics": [
                {"namespace": "payments", "workload": "2 pods", "rx_bytes_per_sec": 2048, "tx_bytes_per_sec": 1024, "connections": 7, "source": "prometheus"}
            ],
        },
    )

    assert response.status_code == 200
    row = db_session.query(NetworkUsage).filter(NetworkUsage.cluster == "network-cluster").first()
    assert row.namespace == "payments"
    assert row.rx_bytes_per_sec == 2048
    dashboard = client.get("/api/dashboard")
    network_rows = [item for item in dashboard.json()["networkUsage"] if item["cluster"] == "network-cluster"]
    assert network_rows[0]["source"] == "prometheus"
