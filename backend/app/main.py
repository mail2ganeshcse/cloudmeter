import base64
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import pbkdf2_hmac, sha256
from secrets import token_hex, token_urlsafe
from typing import Any
from urllib.parse import urlencode

import certifi
import requests
from google.auth.exceptions import GoogleAuthError, TransportError
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import inspect, text, func
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db
from pydantic import BaseModel

from .models import (
    AiUsage,
    BudgetAlert,
    CloudIntegration,
    CloudSpend,
    ClusterConnection,
    ClusterNodeInventory,
    Customer,
    Invoice,
    KubernetesCost,
    NetworkUsage,
    UserAccount,
    UserSession,
)
from .seed import seed_if_empty
from .settings import settings

app = FastAPI(title="CloudMeter AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_user_account_columns()
    ensure_owner_columns()
    with SessionLocal() as db:
        seed_if_empty(db)


def money(value: float | None) -> int:
    return round(value or 0)


CLOUD_INSTANCE_HOURLY_USD = {
    "t2.micro": 0.0116,
    "t2.small": 0.023,
    "t2.medium": 0.0464,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m6i.large": 0.096,
    "m6i.xlarge": 0.192,
    "m6i.2xlarge": 0.384,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "c6i.large": 0.085,
    "c6i.xlarge": 0.17,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
    "r6i.large": 0.126,
    "r6i.xlarge": 0.252,
}
USD_TO_INR = 83


def estimate_node_hourly_inr(instance_type: str, cpu_allocatable: float, memory_gib: float) -> float:
    normalized_type = (instance_type or "").strip().lower()
    if normalized_type in CLOUD_INSTANCE_HOURLY_USD:
        return round(CLOUD_INSTANCE_HOURLY_USD[normalized_type] * USD_TO_INR, 2)
    return round((cpu_allocatable * 2.8) + (memory_gib * 0.35), 2)


def cloud_secret_key() -> bytes:
    material = settings.cloud_credentials_secret or settings.database_url or settings.session_cookie_name
    return sha256(material.encode("utf-8")).digest()


def protect_cloud_credentials(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    key = cloud_secret_key()
    encrypted = bytes(value ^ key[index % len(key)] for index, value in enumerate(raw))
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def credential_hint(payload: dict[str, str]) -> str:
    for key in ("access_key", "client_id", "account_id", "tenant_id", "project_id"):
        value = (payload.get(key) or "").strip()
        if value:
            return f"{value[:4]}...{value[-4:]}" if len(value) > 8 else value
    return "stored"


def cloud_integration_payload(integration: CloudIntegration) -> dict[str, Any]:
    return {
        "id": integration.id,
        "provider": integration.provider,
        "displayName": integration.display_name,
        "accountId": integration.account_id,
        "region": integration.region,
        "billingSource": integration.billing_source,
        "credentialHint": integration.credential_hint,
        "status": integration.status,
        "lastCheckedAt": integration.last_checked_at.isoformat(),
    }


class GoogleLoginRequest(BaseModel):
    credential: str
    username: str | None = None
    password: str | None = None


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


class SetPasswordRequest(BaseModel):
    password: str


class ProfileSetupRequest(BaseModel):
    first_name: str
    last_name: str
    country_code: str = "+91"
    phone_number: str = ""


class UserRoleUpdateRequest(BaseModel):
    role: str


class CloudIntegrationRequest(BaseModel):
    provider: str
    display_name: str = ""
    account_id: str = ""
    region: str = ""
    billing_source: str = ""
    access_key: str = ""
    secret_key: str = ""
    tenant_id: str = ""
    client_id: str = ""
    private_key: str = ""
    service_account_json: str = ""


class ClusterCreateRequest(BaseModel):
    cluster_name: str
    provider: str
    environment: str = "Production"


class AgentHeartbeatRequest(BaseModel):
    token: str
    cluster_name: str
    provider: str = "Kubernetes"
    status: str = "connected"


class NamespaceSnapshot(BaseModel):
    namespace: str
    pods: int = 0
    cpu_millicores: float = 0
    memory_mib: float = 0


class PodSnapshot(BaseModel):
    namespace: str
    pod: str
    cpu_millicores: float = 0
    memory_mib: float = 0


class NodeSnapshot(BaseModel):
    name: str
    instance_type: str = "unknown"
    zone: str = "unknown"
    provider_id: str = ""
    cpu_allocatable: float = 0
    memory_mib: float = 0


class AgentSnapshotRequest(BaseModel):
    token: str
    cluster_name: str
    provider: str = "Kubernetes"
    node_count: int = 0
    pod_count: int = 0
    namespaces: list[NamespaceSnapshot] = []
    pods: list[PodSnapshot] = []
    nodes: list[NodeSnapshot] = []


class NetworkMetric(BaseModel):
    namespace: str
    workload: str = "namespace"
    rx_bytes_per_sec: float = 0
    tx_bytes_per_sec: float = 0
    connections: int = 0
    source: str = "inventory"


class AgentNetworkRequest(BaseModel):
    token: str
    cluster_name: str
    provider: str = "Kubernetes"
    metrics: list[NetworkMetric] = []


def cluster_install_command(cluster: ClusterConnection) -> str:
    return (
        "CLOUDMETER_TOKEN={token} CLOUDMETER_CLUSTER={cluster} "
        "CLOUDMETER_PROVIDER='{provider}' "
        "/bin/bash -c \"$(curl -fsSL {public_api_url}/api/agent/install.sh)\""
    ).format(
        token=cluster.token,
        cluster=cluster.cluster_name,
        provider=cluster.provider,
        public_api_url=settings.public_api_url.rstrip("/"),
    )


def cluster_slug(name: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in name)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")[:48]
    return cleaned or "default"


def cluster_verify_command(cluster: ClusterConnection) -> str:
    return f"kubectl get pods -n cloudmeter-agent -l app.kubernetes.io/instance={cluster_slug(cluster.cluster_name)}"


def onboarding_cluster_payload(cluster: ClusterConnection) -> dict[str, Any]:
    return {
        "id": cluster.id,
        "customerId": cluster.customer_id,
        "clusterName": cluster.cluster_name,
        "provider": cluster.provider,
        "environment": cluster.environment,
        "status": cluster.status,
        "agentMode": cluster.agent_mode,
        "lastSeen": cluster.last_seen,
        "installCommand": cluster_install_command(cluster),
        "verifyCommand": cluster_verify_command(cluster),
    }


def workspace_customer_for_user(user: UserAccount, db: Session) -> Customer:
    customer_name = f"{user.email} workspace"
    customer = db.query(Customer).filter(Customer.name == customer_name).first()
    if customer:
        return customer
    customer = Customer(
        name=customer_name,
        segment="Workspace",
        region=user.hosted_domain or "Private",
        billing_model="User-owned cloud and Kubernetes billing",
    )
    db.add(customer)
    db.flush()
    return customer


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def ensure_user_account_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("user_accounts"):
        return
    existing = {column["name"] for column in inspector.get_columns("user_accounts")}
    ddl = {
        "username": "ALTER TABLE user_accounts ADD COLUMN username VARCHAR(180) DEFAULT ''",
        "github_sub": "ALTER TABLE user_accounts ADD COLUMN github_sub VARCHAR(120) DEFAULT ''",
        "sso_sub": "ALTER TABLE user_accounts ADD COLUMN sso_sub VARCHAR(180) DEFAULT ''",
        "password_salt": "ALTER TABLE user_accounts ADD COLUMN password_salt VARCHAR(80) DEFAULT ''",
        "password_hash": "ALTER TABLE user_accounts ADD COLUMN password_hash VARCHAR(160) DEFAULT ''",
        "first_name": "ALTER TABLE user_accounts ADD COLUMN first_name VARCHAR(80) DEFAULT ''",
        "last_name": "ALTER TABLE user_accounts ADD COLUMN last_name VARCHAR(80) DEFAULT ''",
        "country_code": "ALTER TABLE user_accounts ADD COLUMN country_code VARCHAR(12) DEFAULT '+91'",
        "phone_number": "ALTER TABLE user_accounts ADD COLUMN phone_number VARCHAR(40) DEFAULT ''",
        "onboarding_complete": "ALTER TABLE user_accounts ADD COLUMN onboarding_complete BOOLEAN DEFAULT FALSE",
    }
    with engine.begin() as connection:
        for column, statement in ddl.items():
            if column not in existing:
                connection.execute(text(statement))


def ensure_owner_columns() -> None:
    inspector = inspect(engine)
    table_columns = {
        "cluster_connections": "ALTER TABLE cluster_connections ADD COLUMN owner_user_id INTEGER DEFAULT 0",
        "kubernetes_costs": "ALTER TABLE kubernetes_costs ADD COLUMN owner_user_id INTEGER DEFAULT 0",
        "network_usage": "ALTER TABLE network_usage ADD COLUMN owner_user_id INTEGER DEFAULT 0",
    }
    with engine.begin() as connection:
        for table, statement in table_columns.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            if "owner_user_id" not in existing:
                connection.execute(text(statement))


def hash_password(password: str, salt: str) -> str:
    return pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 180_000).hex()


def set_local_password(user: UserAccount, username: str, password: str) -> None:
    cleaned_username = username.strip().lower()
    if len(cleaned_username) < 3 or "@" not in cleaned_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use a valid email as username")
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")
    salt = token_hex(16)
    user.username = cleaned_username
    user.password_salt = salt
    user.password_hash = hash_password(password, salt)


def password_matches(user: UserAccount, password: str) -> bool:
    if not user.password_salt or not user.password_hash:
        return False
    return hash_password(password, user.password_salt) == user.password_hash


def role_for_email(email: str) -> str:
    normalized = email.lower()
    if normalized == "raashviroyal@gmail.com":
        return "superadmin"
    domain = normalized.split("@")[-1] if "@" in normalized else ""
    return "admin" if domain in {"cloudmeter.ai", "example.com"} else "viewer"


def limits_for_role(role: str) -> dict[str, bool | int]:
    full_access = role in {"admin", "superadmin"}
    return {
        "canViewDashboard": True,
        "canCreateInvoices": full_access,
        "canConnectClusters": True,
        "canManageUsers": role == "superadmin",
        "maxClusters": 1 if role == "viewer" else 999,
        "dataRetentionDays": 7 if role == "viewer" else 3650,
    }


def create_session_for_user(user: UserAccount, response: Response, db: Session) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    user.last_login_at = now
    session_token = token_urlsafe(32)
    expires_at = now + timedelta(days=settings.session_ttl_days)
    db.flush()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(session_token),
            created_at=now,
            expires_at=expires_at,
            revoked=False,
        )
    )
    db.commit()
    db.refresh(user)
    set_session_cookie(response, session_token, expires_at)
    return session_token, expires_at


def session_payload(user: UserAccount, session_token: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session": {
            "provider": user.provider,
            "role": user.role,
            "plan": "limited" if user.role == "viewer" else "master" if user.role == "superadmin" else "workspace",
        },
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "avatar": user.avatar,
            "username": user.username or user.email,
            "hasPassword": bool(user.password_hash),
            "firstName": user.first_name,
            "lastName": user.last_name,
            "countryCode": user.country_code,
            "phoneNumber": user.phone_number,
            "onboardingComplete": user.onboarding_complete,
        },
        "limits": limits_for_role(user.role),
    }
    if session_token:
        payload["session"]["accessToken"] = session_token
    return payload


def managed_user_payload(account: UserAccount, sessions_by_user: dict[int, int]) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "avatar": account.avatar,
        "role": account.role,
        "provider": account.provider,
        "hostedDomain": account.hosted_domain,
        "firstLoginAt": account.first_login_at.isoformat(),
        "lastLoginAt": account.last_login_at.isoformat(),
        "sessions": sessions_by_user.get(account.id, 0),
    }


def upsert_oauth_user(
    db: Session,
    *,
    provider: str,
    subject: str,
    email: str,
    name: str,
    avatar: str = "",
    hosted_domain: str = "",
) -> UserAccount:
    normalized_email = email.strip().lower()
    if not subject or not normalized_email or "@" not in normalized_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OAuth provider did not return a usable identity")

    subject_column = {
        "google": UserAccount.google_sub,
        "github": UserAccount.github_sub,
        "sso": UserAccount.sso_sub,
    }[provider]
    user = db.query(UserAccount).filter(subject_column == subject).first()
    if not user:
        user = db.query(UserAccount).filter(UserAccount.email == normalized_email).first()

    now = datetime.now(UTC)
    role = role_for_email(normalized_email)
    if not user:
        user = UserAccount(
            google_sub=subject if provider == "google" else f"{provider}:{subject}",
            github_sub=subject if provider == "github" else "",
            sso_sub=subject if provider == "sso" else "",
            email=normalized_email,
            username=normalized_email,
            name=name or normalized_email.split("@")[0],
            avatar=avatar,
            role=role,
            provider=provider,
            hosted_domain=hosted_domain,
            first_login_at=now,
            last_login_at=now,
        )
        db.add(user)
        return user

    if provider == "google":
        user.google_sub = subject
    elif provider == "github":
        user.github_sub = subject
    elif provider == "sso":
        user.sso_sub = subject
    user.email = normalized_email
    user.username = user.username or normalized_email
    user.name = name or user.name
    user.avatar = avatar or user.avatar
    if role == "superadmin":
        user.role = role
    user.provider = provider
    user.hosted_domain = hosted_domain
    user.last_login_at = now
    return user


def set_session_cookie(response: Response, session_token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        expires=expires_at,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def current_user_from_cookie(request: Request, db: Session) -> tuple[UserAccount, UserSession]:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    now = datetime.now(UTC)
    user_session = (
        db.query(UserSession)
        .filter(
            UserSession.token_hash == token_hash(raw_token),
            UserSession.revoked.is_(False),
            UserSession.expires_at > now,
        )
        .first()
    )
    if not user_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = db.query(UserAccount).filter(UserAccount.id == user_session.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user, user_session


def verify_google_credential(credential: str) -> dict[str, Any]:
    if credential.count(".") != 2:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token verification failed")

    session = requests.Session()
    session.verify = certifi.where()
    google_request = google_requests.Request(session=session)
    try:
        return id_token.verify_oauth2_token(credential, google_request, settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token verification failed") from exc
    except TransportError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to reach Google token verification service") from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token verification failed") from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/google")
def google_login(payload: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google client ID is not configured")

    claims = verify_google_credential(payload.credential)

    email = str(claims.get("email", "")).lower()
    google_sub = str(claims.get("sub", ""))
    if not google_sub or not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token is missing identity claims")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")

    user = upsert_oauth_user(
        db,
        provider="google",
        subject=google_sub,
        email=email,
        name=str(claims.get("name") or email.split("@")[0]),
        avatar=str(claims.get("picture") or ""),
        hosted_domain=str(claims.get("hd") or ""),
    )

    if payload.username and payload.password:
        if payload.username.strip().lower() != email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username must match the verified Google email")
        set_local_password(user, payload.username, payload.password)

    session_token, _ = create_session_for_user(user, response, db)
    return session_payload(user, session_token)


@app.get("/api/auth/github/start")
def github_start() -> RedirectResponse:
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GitHub OAuth is not configured")
    state = token_urlsafe(24)
    redirect_uri = f"{settings.public_api_url.rstrip('/')}/api/auth/github/callback"
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    response = RedirectResponse(url)
    response.set_cookie("cloudmeter_github_state", state, httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=600, path="/")
    return response


@app.get("/api/auth/github/callback")
def github_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    expected_state = request.cookies.get("cloudmeter_github_state")
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid GitHub OAuth state")

    token_response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": f"{settings.public_api_url.rstrip('/')}/api/auth/github/callback",
        },
        timeout=15,
    )
    token_response.raise_for_status()
    access_token = token_response.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub OAuth did not return an access token")

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
    profile = requests.get("https://api.github.com/user", headers=headers, timeout=15)
    profile.raise_for_status()
    profile_body = profile.json()
    emails = requests.get("https://api.github.com/user/emails", headers=headers, timeout=15)
    emails.raise_for_status()
    email_rows = emails.json()
    primary_email = next((row["email"] for row in email_rows if row.get("primary") and row.get("verified")), "")
    if not primary_email:
        primary_email = next((row["email"] for row in email_rows if row.get("verified")), "")
    if not primary_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub account needs a verified email")

    user = upsert_oauth_user(
        db,
        provider="github",
        subject=str(profile_body.get("id") or ""),
        email=primary_email,
        name=str(profile_body.get("name") or profile_body.get("login") or primary_email.split("@")[0]),
        avatar=str(profile_body.get("avatar_url") or ""),
    )
    response = RedirectResponse(settings.frontend_url.rstrip("/"))
    create_session_for_user(user, response, db)
    response.delete_cookie("cloudmeter_github_state", path="/")
    return response


@app.get("/api/auth/sso/start")
def sso_start() -> RedirectResponse:
    if not all([settings.sso_client_id, settings.sso_client_secret, settings.sso_authorize_url, settings.sso_token_url, settings.sso_userinfo_url]):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="SSO OIDC is not configured")
    state = token_urlsafe(24)
    redirect_uri = f"{settings.public_api_url.rstrip('/')}/api/auth/sso/callback"
    url = settings.sso_authorize_url + ("&" if "?" in settings.sso_authorize_url else "?") + urlencode(
        {
            "client_id": settings.sso_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
    )
    response = RedirectResponse(url)
    response.set_cookie("cloudmeter_sso_state", state, httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=600, path="/")
    return response


@app.get("/api/auth/sso/callback")
def sso_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    expected_state = request.cookies.get("cloudmeter_sso_state")
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid SSO state")

    token_response = requests.post(
        settings.sso_token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": settings.sso_client_id,
            "client_secret": settings.sso_client_secret,
            "code": code,
            "redirect_uri": f"{settings.public_api_url.rstrip('/')}/api/auth/sso/callback",
        },
        timeout=15,
    )
    token_response.raise_for_status()
    access_token = token_response.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SSO did not return an access token")

    profile = requests.get(settings.sso_userinfo_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    profile.raise_for_status()
    claims = profile.json()
    email = str(claims.get("email") or "").lower()
    subject = str(claims.get("sub") or "")
    if not email or not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SSO profile is missing email or subject")
    if claims.get("email_verified") is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SSO email is not verified")

    user = upsert_oauth_user(
        db,
        provider="sso",
        subject=subject,
        email=email,
        name=str(claims.get("name") or email.split("@")[0]),
        avatar=str(claims.get("picture") or ""),
        hosted_domain=email.split("@")[-1],
    )
    response = RedirectResponse(settings.frontend_url.rstrip("/"))
    create_session_for_user(user, response, db)
    response.delete_cookie("cloudmeter_sso_state", path="/")
    return response


@app.post("/api/auth/login")
def password_login(payload: PasswordLoginRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    username = payload.username.strip().lower()
    user = db.query(UserAccount).filter((UserAccount.username == username) | (UserAccount.email == username)).first()
    if not user or not password_matches(user, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    session_token, _ = create_session_for_user(user, response, db)
    return session_payload(user, session_token)


@app.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    return session_payload(user)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        db.query(UserSession).filter(UserSession.token_hash == token_hash(raw_token)).update({"revoked": True})
        db.commit()
    clear_session_cookie(response)
    return {"status": "ok"}


@app.post("/api/auth/password")
def set_password(payload: SetPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    set_local_password(user, user.email, payload.password)
    db.commit()
    db.refresh(user)
    return session_payload(user)


@app.post("/api/auth/profile")
def set_profile(payload: ProfileSetupRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    first_name = payload.first_name.strip()
    last_name = payload.last_name.strip()
    country_code = payload.country_code.strip() or "+91"
    phone_number = payload.phone_number.strip()
    if len(first_name) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="First name is required")
    if len(last_name) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Last name is required")
    if not country_code.startswith("+") or len(country_code) > 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use a valid country code")

    user.first_name = first_name
    user.last_name = last_name
    user.country_code = country_code
    user.phone_number = phone_number
    user.name = f"{first_name} {last_name}".strip()
    db.commit()
    db.refresh(user)
    return session_payload(user)


@app.post("/api/auth/onboarding/complete")
def complete_onboarding(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    user.onboarding_complete = True
    db.commit()
    db.refresh(user)
    return session_payload(user)


@app.get("/api/users")
def users(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    if user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin access required")

    users_rows = db.query(UserAccount).order_by(UserAccount.last_login_at.desc()).all()
    sessions_by_user = {
        row[0]: row[1]
        for row in db.query(UserSession.user_id, func.count(UserSession.id))
        .group_by(UserSession.user_id)
        .all()
    }
    return {
        "users": [managed_user_payload(account, sessions_by_user) for account in users_rows]
    }


@app.patch("/api/users/{user_id}/role")
def update_user_role(user_id: int, payload: UserRoleUpdateRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    actor, _ = current_user_from_cookie(request, db)
    if actor.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin access required")

    role = payload.role.strip().lower()
    if role not in {"viewer", "admin", "superadmin"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be viewer, admin, or superadmin")

    target = db.query(UserAccount).filter(UserAccount.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.email.lower() == "raashviroyal@gmail.com" and role != "superadmin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Master superadmin account cannot be demoted")

    target.role = role
    db.commit()
    db.refresh(target)
    sessions_by_user = {
        row[0]: row[1]
        for row in db.query(UserSession.user_id, func.count(UserSession.id))
        .group_by(UserSession.user_id)
        .all()
    }
    return {"user": managed_user_payload(target, sessions_by_user)}


@app.get("/api/cloud/integrations")
def cloud_integrations(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    rows = (
        db.query(CloudIntegration)
        .filter(CloudIntegration.owner_user_id == user.id)
        .order_by(CloudIntegration.updated_at.desc())
        .all()
    )
    return {"integrations": [cloud_integration_payload(row) for row in rows]}


@app.post("/api/cloud/integrations")
def create_cloud_integration(payload: CloudIntegrationRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    provider = payload.provider.strip().upper()
    if provider not in {"AWS", "GCP", "OCI", "AZURE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider must be AWS, GCP, OCI, or Azure")

    credentials = {
        "access_key": payload.access_key.strip(),
        "secret_key": payload.secret_key.strip(),
        "tenant_id": payload.tenant_id.strip(),
        "client_id": payload.client_id.strip(),
        "private_key": payload.private_key.strip(),
        "service_account_json": payload.service_account_json.strip(),
        "account_id": payload.account_id.strip(),
        "region": payload.region.strip(),
        "billing_source": payload.billing_source.strip(),
    }
    has_secret = any(credentials[key] for key in ("secret_key", "private_key", "service_account_json"))
    has_identifier = any(credentials[key] for key in ("access_key", "client_id", "account_id", "tenant_id"))
    if not has_secret or not has_identifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add the provider account identifier and secret material")

    customer = workspace_customer_for_user(user, db)
    now = datetime.now(UTC)
    integration = CloudIntegration(
        customer_id=customer.id,
        owner_user_id=user.id,
        provider=provider,
        display_name=payload.display_name.strip() or f"{provider} billing connector",
        account_id=payload.account_id.strip(),
        region=payload.region.strip() or "global",
        billing_source=payload.billing_source.strip(),
        credential_hint=credential_hint(credentials),
        credential_blob=protect_cloud_credentials(credentials),
        status="configured",
        last_checked_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return {"integration": cloud_integration_payload(integration)}


@app.get("/api/onboarding")
def onboarding(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    clusters = (
        db.query(ClusterConnection)
        .filter(ClusterConnection.owner_user_id == user.id, ~ClusterConnection.token.like("%_demo"))
        .order_by(ClusterConnection.id.desc())
        .all()
    )
    return {
        "steps": [
            {"title": "Sign in with Google", "body": "Anyone can enter with a limited viewer workspace. Admins unlock invoices, chargeback edits, and more clusters."},
            {"title": "Add customer or company", "body": "Choose SaaS, MSP, enterprise, AI platform, or on-prem operator and assign billing owners."},
            {"title": "Connect Kubernetes", "body": "Run one read-only curl command from terminal or cloud shell. It installs the CloudMeter agent namespace and service account."},
            {"title": "Attach cloud and AI providers", "body": "Map AWS, GCP, OCI, OpenAI, Claude, Gemini, Mistral, Ollama, storage, GPU, and document usage."},
            {"title": "Generate chargeback and invoices", "body": "Review namespace, team, customer, and AI product bills before sending invoices."},
        ],
        "prerequisites": ["kubectl access to the target cluster", "curl installed", "outbound HTTPS from the cluster", "read-only RBAC approval"],
        "clusters": [onboarding_cluster_payload(c) for c in clusters],
    }


@app.post("/api/onboarding/clusters")
def create_cluster(payload: ClusterCreateRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    customer = workspace_customer_for_user(user, db)
    cluster = ClusterConnection(
        customer_id=customer.id,
        owner_user_id=user.id,
        cluster_name=payload.cluster_name,
        provider=payload.provider,
        environment=payload.environment,
        token=f"cm_{token_urlsafe(22)}",
        status="pending",
    )
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return onboarding_cluster_payload(cluster)


@app.post("/api/onboarding/clusters/{cluster_id}/verify")
def verify_cluster(cluster_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    cluster = db.query(ClusterConnection).filter(ClusterConnection.id == cluster_id, ClusterConnection.owner_user_id == user.id).first()
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster setup not found")
    connected = cluster.status == "connected" and bool(cluster.last_seen)
    return {
        "verified": connected,
        "message": f"{cluster.cluster_name} is connected and reporting." if connected else f"{cluster.cluster_name} has not reported yet. Run the install command, then verify again.",
        "cluster": onboarding_cluster_payload(cluster),
    }


@app.post("/api/agent/heartbeat")
def agent_heartbeat(payload: AgentHeartbeatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    cluster = db.query(ClusterConnection).filter(ClusterConnection.token == payload.token).first()
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster token is not registered")
    else:
        cluster.cluster_name = payload.cluster_name or cluster.cluster_name
        cluster.provider = payload.provider or cluster.provider
        cluster.status = payload.status
        cluster.last_seen = datetime.now(UTC).isoformat()
    db.commit()
    db.refresh(cluster)
    return {
        "status": "ok",
        "cluster": {
            "id": cluster.id,
            "clusterName": cluster.cluster_name,
            "provider": cluster.provider,
            "connectionStatus": cluster.status,
            "lastSeen": cluster.last_seen,
        },
    }


@app.post("/api/agent/snapshot")
def agent_snapshot(payload: AgentSnapshotRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    cluster = db.query(ClusterConnection).filter(ClusterConnection.token == payload.token).first()
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster token is not registered")

    cluster.cluster_name = payload.cluster_name or cluster.cluster_name
    cluster.provider = payload.provider or cluster.provider
    cluster.status = "connected"
    cluster.last_seen = datetime.now(UTC).isoformat()

    db.query(KubernetesCost).filter(KubernetesCost.cluster == cluster.cluster_name, KubernetesCost.owner_user_id == cluster.owner_user_id).delete()
    db.query(ClusterNodeInventory).filter(ClusterNodeInventory.cluster == cluster.cluster_name, ClusterNodeInventory.owner_user_id == cluster.owner_user_id).delete()
    month = datetime.now(UTC).strftime("%Y-%m")
    rows_created = 0
    observed_at = datetime.now(UTC)
    for node in payload.nodes:
        if not node.name:
            continue
        memory_gib = round(node.memory_mib / 1024, 3)
        db.add(
            ClusterNodeInventory(
                customer_id=cluster.customer_id,
                owner_user_id=cluster.owner_user_id,
                cluster=cluster.cluster_name,
                node_name=node.name,
                instance_type=node.instance_type or "unknown",
                zone=node.zone or "unknown",
                provider_id=node.provider_id or "",
                cpu_allocatable=round(node.cpu_allocatable, 3),
                memory_gib=memory_gib,
                hourly_inr=estimate_node_hourly_inr(node.instance_type, node.cpu_allocatable, memory_gib),
                observed_at=observed_at,
            )
        )

    for pod in payload.pods:
        if not pod.namespace or not pod.pod:
            continue
        cpu_cores = round(pod.cpu_millicores / 1000, 6)
        memory_gib = round(pod.memory_mib / 1024, 3)
        estimated_amount = round((cpu_cores * 120) + (memory_gib * 35) + 2)
        db.add(
            KubernetesCost(
                customer_id=cluster.customer_id,
                owner_user_id=cluster.owner_user_id,
                cluster=cluster.cluster_name,
                namespace=pod.namespace,
                workload=f"pod/{pod.pod}",
                team=pod.namespace,
                cpu_core_hours=cpu_cores,
                memory_gb_hours=memory_gib,
                gpu_hours=0,
                amount_inr=estimated_amount,
                month=month,
            )
        )
        rows_created += 1

    if rows_created == 0:
        for namespace in payload.namespaces:
            if not namespace.namespace:
                continue
            cpu_cores = round(namespace.cpu_millicores / 1000, 6)
            memory_gib = round(namespace.memory_mib / 1024, 3)
            estimated_amount = round((cpu_cores * 120) + (memory_gib * 35) + (namespace.pods * 10))
            db.add(
                KubernetesCost(
                    customer_id=cluster.customer_id,
                    owner_user_id=cluster.owner_user_id,
                    cluster=cluster.cluster_name,
                    namespace=namespace.namespace,
                    workload=f"{namespace.pods} live pods",
                    team=namespace.namespace,
                    cpu_core_hours=cpu_cores,
                    memory_gb_hours=memory_gib,
                    gpu_hours=0,
                    amount_inr=estimated_amount,
                    month=month,
                )
            )
            rows_created += 1

    if rows_created == 0:
        db.add(
            KubernetesCost(
                customer_id=cluster.customer_id,
                owner_user_id=cluster.owner_user_id,
                cluster=cluster.cluster_name,
                namespace="cluster-summary",
                workload=f"{payload.pod_count} live pods",
                team="Platform",
                cpu_core_hours=0,
                memory_gb_hours=0,
                gpu_hours=0,
                amount_inr=0,
                month=month,
            )
        )
        rows_created = 1

    db.commit()
    db.refresh(cluster)
    return {
        "status": "ok",
        "cluster": {
            "id": cluster.id,
            "clusterName": cluster.cluster_name,
            "provider": cluster.provider,
            "connectionStatus": cluster.status,
            "lastSeen": cluster.last_seen,
            "nodeCount": payload.node_count,
            "podCount": payload.pod_count,
            "namespaces": rows_created,
        },
    }


@app.post("/api/agent/network")
def agent_network(payload: AgentNetworkRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    cluster = db.query(ClusterConnection).filter(ClusterConnection.token == payload.token).first()
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster token is not registered")

    cluster.status = "connected"
    cluster.last_seen = datetime.now(UTC).isoformat()
    db.query(NetworkUsage).filter(NetworkUsage.cluster == cluster.cluster_name, NetworkUsage.owner_user_id == cluster.owner_user_id).delete()
    observed_at = datetime.now(UTC)
    rows_created = 0
    for metric in payload.metrics:
        if not metric.namespace:
            continue
        db.add(
            NetworkUsage(
                customer_id=cluster.customer_id,
                owner_user_id=cluster.owner_user_id,
                cluster=cluster.cluster_name,
                namespace=metric.namespace,
                workload=metric.workload or "namespace",
                rx_bytes_per_sec=metric.rx_bytes_per_sec,
                tx_bytes_per_sec=metric.tx_bytes_per_sec,
                connections=metric.connections,
                source=metric.source,
                observed_at=observed_at,
            )
        )
        rows_created += 1
    db.commit()
    db.refresh(cluster)
    return {
        "status": "ok",
        "cluster": cluster.cluster_name,
        "networkRows": rows_created,
        "observedAt": observed_at.isoformat(),
    }


@app.get("/api/agent/install.sh", response_class=PlainTextResponse)
def agent_install_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

API_URL="${CLOUDMETER_API_URL:-https://cloudmeter.in}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required before installing the CloudMeter agent."
  exit 1
fi

if [ -z "${CLOUDMETER_TOKEN:-}" ] || [ -z "${CLOUDMETER_CLUSTER:-}" ]; then
  echo "CLOUDMETER_TOKEN and CLOUDMETER_CLUSTER are required."
  exit 1
fi

CLUSTER_SLUG="$(printf '%s' "${CLOUDMETER_CLUSTER}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/^-*//;s/-*$//;s/--*/-/g' | cut -c1-48)"
if [ -z "${CLUSTER_SLUG}" ]; then
  CLUSTER_SLUG="default"
fi
AGENT_NAME="cloudmeter-agent-${CLUSTER_SLUG}"

curl -fsSL -X POST "${API_URL}/api/agent/heartbeat" \
  -H "Content-Type: application/json" \
  -d '{"token":"'"${CLOUDMETER_TOKEN}"'","cluster_name":"'"${CLOUDMETER_CLUSTER}"'","provider":"'"${CLOUDMETER_PROVIDER:-Kubernetes}"'","status":"installing"}' >/dev/null || true

kubectl create namespace cloudmeter-agent --dry-run=client -o yaml | kubectl apply -f -
kubectl create serviceaccount cloudmeter-agent -n cloudmeter-agent --dry-run=client -o yaml | kubectl apply -f -
cat <<'EOF' | sed \
  -e "s#__AGENT_NAME__#${AGENT_NAME}#g" \
  -e "s#__CLUSTER_SLUG__#${CLUSTER_SLUG}#g" \
  -e "s#__CLOUDMETER_TOKEN__#${CLOUDMETER_TOKEN}#g" \
  -e "s#__CLOUDMETER_CLUSTER__#${CLOUDMETER_CLUSTER}#g" \
  -e "s#__CLOUDMETER_PROVIDER__#${CLOUDMETER_PROVIDER:-Kubernetes}#g" \
  -e "s#__API_URL__#${API_URL}#g" \
  | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cloudmeter-readonly
rules:
  - apiGroups: ["", "apps", "batch", "metrics.k8s.io"]
    resources: ["pods", "nodes", "namespaces", "deployments", "statefulsets", "daemonsets", "jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["metrics.k8s.io"]
    resources: ["pods", "nodes"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["nodes/proxy"]
    verbs: ["get"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["cilium.io"]
    resources: ["ciliumendpoints", "ciliumnetworkpolicies"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cloudmeter-readonly
subjects:
  - kind: ServiceAccount
    name: cloudmeter-agent
    namespace: cloudmeter-agent
roleRef:
  kind: ClusterRole
  name: cloudmeter-readonly
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: __AGENT_NAME__
  namespace: cloudmeter-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: cloudmeter-agent
      app.kubernetes.io/instance: __CLUSTER_SLUG__
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cloudmeter-agent
        app.kubernetes.io/instance: __CLUSTER_SLUG__
    spec:
      serviceAccountName: cloudmeter-agent
      containers:
        - name: agent
          image: alpine/k8s:1.31.0
          command:
            - sh
            - -c
            - |
              agent_api_url="${CLOUDMETER_API_URL:-https://cloudmeter.in}"
              cpu_to_mcores() {
                value="$1"
                case "$value" in
                  *n) awk "BEGIN {printf \\"%.3f\\", substr(\\"$value\\",1,length(\\"$value\\")-1)/1000000}" ;;
                  *u) awk "BEGIN {printf \\"%.3f\\", substr(\\"$value\\",1,length(\\"$value\\")-1)/1000}" ;;
                  *m) printf "%s" "${value%m}" ;;
                  *) awk "BEGIN {printf \\"%.3f\\", \\"$value\\"*1000}" ;;
                esac
              }
              mem_to_mib() {
                value="$1"
                case "$value" in
                  *Ki) awk "BEGIN {printf \\"%.3f\\", substr(\\"$value\\",1,length(\\"$value\\")-2)/1024}" ;;
                  *Mi) printf "%s" "${value%Mi}" ;;
                  *Gi) awk "BEGIN {printf \\"%.3f\\", substr(\\"$value\\",1,length(\\"$value\\")-2)*1024}" ;;
                  *) printf "0" ;;
                esac
              }
              post_snapshot() {
                node_count="$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')"
                pod_count="$(kubectl get pods -A --no-headers 2>/dev/null | wc -l | tr -d ' ')"
                pod_counts="$(kubectl get pods -A --no-headers 2>/dev/null | awk '{count[$1]++} END {for (ns in count) print ns, count[ns]}')"
                metrics="$(kubectl top pods -A --no-headers 2>/dev/null || true)"
                nodes_json="$(kubectl get nodes -o custom-columns=NAME:.metadata.name,TYPE:.metadata.labels.node\\.kubernetes\\.io/instance-type,BETA_TYPE:.metadata.labels.beta\\.kubernetes\\.io/instance-type,ZONE:.metadata.labels.topology\\.kubernetes\\.io/zone,BETA_ZONE:.metadata.labels.failure-domain\\.beta\\.kubernetes\\.io/zone,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory,PROVIDER:.spec.providerID --no-headers 2>/dev/null | awk '
                  function cpu(v) {
                    if (v ~ /n$/) return substr(v,1,length(v)-1)/1000000000;
                    if (v ~ /u$/) return substr(v,1,length(v)-1)/1000000;
                    if (v ~ /m$/) return substr(v,1,length(v)-1)/1000;
                    return v+0;
                  }
                  function mem(v) {
                    if (v ~ /Ki$/) return substr(v,1,length(v)-2)/1024;
                    if (v ~ /Mi$/) return substr(v,1,length(v)-2);
                    if (v ~ /Gi$/) return substr(v,1,length(v)-2)*1024;
                    return 0;
                  }
                  function clean(v) { if (v == "<none>" || v == "") return "unknown"; gsub(/"/, "", v); return v; }
                  function first_known(a, b) { a=clean(a); b=clean(b); return a != "unknown" ? a : b; }
                  NF >= 7 {
                    if (!first_seen) { first_seen=1 } else { printf "," }
                    printf "{\\"name\\":\\"%s\\",\\"instance_type\\":\\"%s\\",\\"zone\\":\\"%s\\",\\"cpu_allocatable\\":%.3f,\\"memory_mib\\":%.3f,\\"provider_id\\":\\"%s\\"}", clean($1), first_known($2, $3), first_known($4, $5), cpu($6), mem($7), clean($8);
                  }')"
                namespaces_json=""
                pods_json=""
                if [ -n "$metrics" ]; then
                  namespaces_json="$(printf '%s\\n' "$metrics" | awk '
                    function cpu(v) {
                      if (v ~ /n$/) return substr(v,1,length(v)-1)/1000000;
                      if (v ~ /u$/) return substr(v,1,length(v)-1)/1000;
                      if (v ~ /m$/) return substr(v,1,length(v)-1);
                      return v*1000;
                    }
                    function mem(v) {
                      if (v ~ /Ki$/) return substr(v,1,length(v)-2)/1024;
                      if (v ~ /Mi$/) return substr(v,1,length(v)-2);
                      if (v ~ /Gi$/) return substr(v,1,length(v)-2)*1024;
                      return 0;
                    }
                    { pods[$1]++; cpu_sum[$1]+=cpu($3); mem_sum[$1]+=mem($4); }
                    END {
                      first=1;
                      for (ns in pods) {
                        if (!first) printf ",";
                        first=0;
                        printf "{\\"namespace\\":\\"%s\\",\\"pods\\":%d,\\"cpu_millicores\\":%.3f,\\"memory_mib\\":%.3f}", ns, pods[ns], cpu_sum[ns], mem_sum[ns];
                      }
                    }')"
                  pods_json="$(printf '%s\\n' "$metrics" | awk '
                    function cpu(v) {
                      if (v ~ /n$/) return substr(v,1,length(v)-1)/1000000;
                      if (v ~ /u$/) return substr(v,1,length(v)-1)/1000;
                      if (v ~ /m$/) return substr(v,1,length(v)-1);
                      return v*1000;
                    }
                    function mem(v) {
                      if (v ~ /Ki$/) return substr(v,1,length(v)-2)/1024;
                      if (v ~ /Mi$/) return substr(v,1,length(v)-2);
                      if (v ~ /Gi$/) return substr(v,1,length(v)-2)*1024;
                      return 0;
                    }
                    {
                      if (!first_seen) { first_seen=1 } else { printf "," }
                      printf "{\\"namespace\\":\\"%s\\",\\"pod\\":\\"%s\\",\\"cpu_millicores\\":%.3f,\\"memory_mib\\":%.3f}", $1, $2, cpu($3), mem($4);
                    }')"
                else
                  namespaces_json="$(printf '%s\\n' "$pod_counts" | awk '
                    NF >= 2 {
                      if (!first_seen) { first_seen=1 } else { printf "," }
                      printf "{\\"namespace\\":\\"%s\\",\\"pods\\":%d,\\"cpu_millicores\\":0,\\"memory_mib\\":0}", $1, $2;
                    }')"
                  pods_json="$(kubectl get pods -A --no-headers 2>/dev/null | awk '
                    NF >= 2 {
                      if (!first_seen) { first_seen=1 } else { printf "," }
                      printf "{\\"namespace\\":\\"%s\\",\\"pod\\":\\"%s\\",\\"cpu_millicores\\":0,\\"memory_mib\\":0}", $1, $2;
                    }')"
                fi
                payload="{\\"token\\":\\"${CLOUDMETER_TOKEN}\\",\\"cluster_name\\":\\"${CLOUDMETER_CLUSTER}\\",\\"provider\\":\\"${CLOUDMETER_PROVIDER:-Kubernetes}\\",\\"node_count\\":${node_count:-0},\\"pod_count\\":${pod_count:-0},\\"namespaces\\":[${namespaces_json}],\\"pods\\":[${pods_json}],\\"nodes\\":[${nodes_json}]}"
                curl -fsSL -X POST "${agent_api_url}/api/agent/snapshot" -H "Content-Type: application/json" -d "$payload" || true
              }
              while true; do
                wget -qO- --header='Content-Type: application/json' --post-data="{\\"token\\":\\"${CLOUDMETER_TOKEN}\\",\\"cluster_name\\":\\"${CLOUDMETER_CLUSTER}\\",\\"provider\\":\\"${CLOUDMETER_PROVIDER:-Kubernetes}\\",\\"status\\":\\"connected\\"}" "${agent_api_url}/api/agent/heartbeat" || true
                post_snapshot
                echo "CloudMeter heartbeat sent for ${CLOUDMETER_CLUSTER}"
                sleep 300
              done
          env:
            - name: CLOUDMETER_TOKEN
              value: "__CLOUDMETER_TOKEN__"
            - name: CLOUDMETER_CLUSTER
              value: "__CLOUDMETER_CLUSTER__"
            - name: CLOUDMETER_PROVIDER
              value: "__CLOUDMETER_PROVIDER__"
            - name: CLOUDMETER_API_URL
              value: "__API_URL__"
EOF

NETWORK_AGENT_NAME="cloudmeter-network-agent-${CLUSTER_SLUG}"
cat <<'EOF' | sed \
  -e "s#__NETWORK_AGENT_NAME__#${NETWORK_AGENT_NAME}#g" \
  -e "s#__CLUSTER_SLUG__#${CLUSTER_SLUG}#g" \
  -e "s#__CLOUDMETER_TOKEN__#${CLOUDMETER_TOKEN}#g" \
  -e "s#__CLOUDMETER_CLUSTER__#${CLOUDMETER_CLUSTER}#g" \
  -e "s#__CLOUDMETER_PROVIDER__#${CLOUDMETER_PROVIDER:-Kubernetes}#g" \
  -e "s#__API_URL__#${API_URL}#g" \
  -e "s#__PROMETHEUS_URL__#${CLOUDMETER_PROMETHEUS_URL:-}#g" \
  | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: __NETWORK_AGENT_NAME__
  namespace: cloudmeter-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: cloudmeter-network-agent
      app.kubernetes.io/instance: __CLUSTER_SLUG__
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cloudmeter-network-agent
        app.kubernetes.io/instance: __CLUSTER_SLUG__
    spec:
      serviceAccountName: cloudmeter-agent
      containers:
        - name: network-agent
          image: python:3.12-alpine
          command:
            - python
            - -u
            - -c
            - |
              import json
              import os
              import ssl
              import time
              import urllib.parse
              import urllib.request

              api_url = os.environ.get("CLOUDMETER_API_URL", "https://cloudmeter.in").rstrip("/")
              token = os.environ["CLOUDMETER_TOKEN"]
              cluster = os.environ["CLOUDMETER_CLUSTER"]
              provider = os.environ.get("CLOUDMETER_PROVIDER", "Kubernetes")
              service_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
              ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
              kube_host = "https://kubernetes.default.svc"

              def http_json(url, headers=None, timeout=8):
                request = urllib.request.Request(url, headers=headers or {})
                context = ssl.create_default_context(cafile=ca_path)
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                  return json.loads(response.read().decode("utf-8"))

              def public_json(url, timeout=8):
                with urllib.request.urlopen(url, timeout=timeout) as response:
                  return json.loads(response.read().decode("utf-8"))

              def post_json(path, payload):
                data = json.dumps(payload).encode("utf-8")
                request = urllib.request.Request(
                  f"{api_url}{path}",
                  data=data,
                  headers={"Content-Type": "application/json"},
                  method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                  response.read()

              def pod_inventory():
                with open(service_token_path, "r", encoding="utf-8") as handle:
                  bearer = handle.read().strip()
                headers = {"Authorization": f"Bearer {bearer}"}
                body = http_json(f"{kube_host}/api/v1/pods", headers=headers)
                counts = {}
                pod_to_ns = {}
                for item in body.get("items", []):
                  namespace = item.get("metadata", {}).get("namespace", "unknown")
                  name = item.get("metadata", {}).get("name", "")
                  counts[namespace] = counts.get(namespace, 0) + 1
                  if name:
                    pod_to_ns[name] = namespace
                return counts, pod_to_ns

              def cluster_nodes():
                with open(service_token_path, "r", encoding="utf-8") as handle:
                  bearer = handle.read().strip()
                headers = {"Authorization": f"Bearer {bearer}"}
                body = http_json(f"{kube_host}/api/v1/nodes", headers=headers)
                return [
                  item.get("metadata", {}).get("name")
                  for item in body.get("items", [])
                  if item.get("metadata", {}).get("name")
                ]

              def prometheus_urls():
                configured = os.environ.get("CLOUDMETER_PROMETHEUS_URL", "").strip()
                urls = [configured] if configured else []
                urls.extend([
                  "http://prometheus-server.monitoring.svc:80",
                  "http://prometheus-operated.monitoring.svc:9090",
                  "http://prometheus.istio-system.svc:9090",
                  "http://prometheus.monitoring.svc:9090",
                ])
                seen = []
                for url in urls:
                  clean = url.rstrip("/")
                  if clean and clean not in seen:
                    seen.append(clean)
                return seen

              def query_prometheus(base_url, query):
                url = f"{base_url}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
                body = public_json(url)
                if body.get("status") != "success":
                  return []
                return body.get("data", {}).get("result", [])

              previous_network = {}
              previous_observed_at = None

              def collect_kubelet_summary(metrics):
                global previous_observed_at
                now = time.time()
                elapsed = max(now - previous_observed_at, 1) if previous_observed_at else 0
                current = {}
                with open(service_token_path, "r", encoding="utf-8") as handle:
                  bearer = handle.read().strip()
                headers = {"Authorization": f"Bearer {bearer}"}
                for node in cluster_nodes():
                  try:
                    summary = http_json(f"{kube_host}/api/v1/nodes/{urllib.parse.quote(node, safe='')}/proxy/stats/summary", headers=headers)
                  except Exception as exc:
                    print(f"Kubelet summary scrape failed for {node}: {exc}", flush=True)
                    continue
                  for pod in summary.get("pods", []):
                    pod_ref = pod.get("podRef", {})
                    namespace = pod_ref.get("namespace")
                    name = pod_ref.get("name")
                    network = pod.get("network") or {}
                    if not namespace or not name:
                      continue
                    key = f"{namespace}/{name}"
                    rx = float(network.get("rxBytes") or 0)
                    tx = float(network.get("txBytes") or 0)
                    current[key] = (namespace, rx, tx)
                    row = metrics.setdefault(namespace, {"namespace": namespace, "workload": "namespace", "rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0, "connections": 0, "source": "kubelet-summary"})
                    if elapsed and key in previous_network:
                      _, old_rx, old_tx = previous_network[key]
                      row["rx_bytes_per_sec"] += max(rx - old_rx, 0) / elapsed
                      row["tx_bytes_per_sec"] += max(tx - old_tx, 0) / elapsed
                    row["source"] = "kubelet-summary"
                previous_network.clear()
                previous_network.update(current)
                previous_observed_at = now
                return metrics

              def collect_network():
                namespace_counts, pod_to_ns = pod_inventory()
                metrics = {
                  namespace: {
                    "namespace": namespace,
                    "workload": f"{count} pods",
                    "rx_bytes_per_sec": 0,
                    "tx_bytes_per_sec": 0,
                    "connections": 0,
                    "source": "inventory",
                  }
                  for namespace, count in namespace_counts.items()
                }
                metrics = collect_kubelet_summary(metrics)
                for base in prometheus_urls():
                  try:
                    rx_rows = query_prometheus(base, 'sum by (namespace) (rate(container_network_receive_bytes_total[5m]))')
                    tx_rows = query_prometheus(base, 'sum by (namespace) (rate(container_network_transmit_bytes_total[5m]))')
                    if not rx_rows and not tx_rows:
                      continue
                    for row in rx_rows:
                      namespace = row.get("metric", {}).get("namespace") or row.get("metric", {}).get("exported_namespace")
                      if namespace:
                        metrics.setdefault(namespace, {"namespace": namespace, "workload": "namespace", "rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0, "connections": 0, "source": "prometheus"})
                        metrics[namespace]["rx_bytes_per_sec"] = float(row.get("value", [0, 0])[1])
                        metrics[namespace]["source"] = "prometheus"
                    for row in tx_rows:
                      namespace = row.get("metric", {}).get("namespace") or row.get("metric", {}).get("exported_namespace")
                      if namespace:
                        metrics.setdefault(namespace, {"namespace": namespace, "workload": "namespace", "rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0, "connections": 0, "source": "prometheus"})
                        metrics[namespace]["tx_bytes_per_sec"] = float(row.get("value", [0, 0])[1])
                        metrics[namespace]["source"] = "prometheus"
                    return list(metrics.values())
                  except Exception as exc:
                    print(f"Prometheus network scrape failed for {base}: {exc}", flush=True)
                return list(metrics.values())

              while True:
                try:
                  payload = {
                    "token": token,
                    "cluster_name": cluster,
                    "provider": provider,
                    "metrics": collect_network(),
                  }
                  post_json("/api/agent/network", payload)
                  print(f"CloudMeter network snapshot sent for {cluster}", flush=True)
                except Exception as exc:
                  print(f"CloudMeter network snapshot failed: {exc}", flush=True)
                time.sleep(300)
          env:
            - name: CLOUDMETER_TOKEN
              value: "__CLOUDMETER_TOKEN__"
            - name: CLOUDMETER_CLUSTER
              value: "__CLOUDMETER_CLUSTER__"
            - name: CLOUDMETER_PROVIDER
              value: "__CLOUDMETER_PROVIDER__"
            - name: CLOUDMETER_API_URL
              value: "__API_URL__"
            - name: CLOUDMETER_PROMETHEUS_URL
              value: "__PROMETHEUS_URL__"
EOF

echo "Waiting for CloudMeter network collector..."
kubectl rollout status -n cloudmeter-agent "deployment/${NETWORK_AGENT_NAME}" --timeout=90s || true
kubectl get pods -n cloudmeter-agent -l app.kubernetes.io/name=cloudmeter-network-agent,app.kubernetes.io/instance="${CLUSTER_SLUG}" || true

curl -fsSL -X POST "${API_URL}/api/agent/heartbeat" \
  -H "Content-Type: application/json" \
  -d '{"token":"'"${CLOUDMETER_TOKEN}"'","cluster_name":"'"${CLOUDMETER_CLUSTER}"'","provider":"'"${CLOUDMETER_PROVIDER:-Kubernetes}"'","status":"connected"}' >/dev/null || true

echo "Waiting for first CloudMeter metrics snapshot..."
kubectl logs -n cloudmeter-agent "deployment/${AGENT_NAME}" --tail=5 --request-timeout=10s 2>/dev/null || true

echo "CloudMeter read-only agent installed for ${CLOUDMETER_CLUSTER}."
echo "Metrics agent: kubectl get pods -n cloudmeter-agent -l app.kubernetes.io/name=cloudmeter-agent,app.kubernetes.io/instance=${CLUSTER_SLUG}"
echo "Network agent: kubectl get pods -n cloudmeter-agent -l app.kubernetes.io/name=cloudmeter-network-agent,app.kubernetes.io/instance=${CLUSTER_SLUG}"
"""


@app.get("/api/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = current_user_from_cookie(request, db)
    customers = db.query(Customer).order_by(Customer.name).all()
    cloud_total = money(db.query(func.sum(CloudSpend.amount_inr)).scalar())
    ai_total = money(db.query(func.sum(AiUsage.amount_inr)).scalar())
    invoice_total = money(db.query(func.sum(Invoice.total_inr)).scalar())
    tokens = money(db.query(func.sum(AiUsage.tokens)).scalar())
    requests = money(db.query(func.sum(AiUsage.requests)).scalar())
    gpu_seconds = money(db.query(func.sum(AiUsage.gpu_seconds)).scalar())
    clusters_by_name = {
        cluster.cluster_name: cluster
        for cluster in db.query(ClusterConnection).filter(ClusterConnection.owner_user_id == user.id).all()
    }
    all_kubernetes_rows = db.query(KubernetesCost).filter(KubernetesCost.owner_user_id == user.id).all()
    def is_live_cluster(cluster_name: str) -> bool:
        cluster = clusters_by_name.get(cluster_name)
        return bool(cluster and cluster.status == "connected" and "T" in cluster.last_seen)

    def is_live_snapshot_row(row: KubernetesCost) -> bool:
        return is_live_cluster(row.cluster) and (row.workload.endswith(" live pods") or row.workload.startswith("pod/"))

    live_kubernetes_rows = [row for row in all_kubernetes_rows if is_live_snapshot_row(row)]
    namespaces = live_kubernetes_rows or all_kubernetes_rows
    namespaces.sort(key=lambda row: (0 if is_live_snapshot_row(row) else 1, row.cluster, row.namespace))
    kube_total = money(sum(row.amount_inr for row in namespaces))
    forecast_total = round((cloud_total + kube_total + ai_total) * 1.16)

    provider_rows = db.query(CloudSpend.provider, func.sum(CloudSpend.amount_inr)).group_by(CloudSpend.provider).all()
    ai_rows = db.query(AiUsage.provider, func.sum(AiUsage.amount_inr), func.sum(AiUsage.tokens), func.sum(AiUsage.requests)).group_by(AiUsage.provider).all()
    ai_usage = db.query(AiUsage).order_by(AiUsage.amount_inr.desc()).all()
    network_usage = (
        db.query(NetworkUsage)
        .filter(NetworkUsage.owner_user_id == user.id)
        .order_by((NetworkUsage.rx_bytes_per_sec + NetworkUsage.tx_bytes_per_sec).desc())
        .all()
    )
    node_inventory = (
        db.query(ClusterNodeInventory)
        .filter(ClusterNodeInventory.owner_user_id == user.id)
        .order_by(ClusterNodeInventory.cluster, ClusterNodeInventory.node_name)
        .all()
    )
    cloud_integrations_rows = (
        db.query(CloudIntegration)
        .filter(CloudIntegration.owner_user_id == user.id)
        .order_by(CloudIntegration.updated_at.desc())
        .all()
    )
    invoices = db.query(Invoice).order_by(Invoice.total_inr.desc()).all()
    alerts = db.query(BudgetAlert).order_by(BudgetAlert.current_inr.desc()).all()

    chargeback = defaultdict(float)
    kubernetes_team_cost = defaultdict(float)
    for row in db.query(CloudSpend.team, CloudSpend.amount_inr).all():
        chargeback[row.team] += row.amount_inr
    for row in namespaces:
        chargeback[row.team] += row.amount_inr
        kubernetes_team_cost[row.team] += row.amount_inr
    for row in db.query(AiUsage.product, AiUsage.amount_inr).all():
        chargeback[row.product] += row.amount_inr

    return {
        "metrics": {
            "total_spend_inr": cloud_total + kube_total + ai_total,
            "cloud_spend_inr": cloud_total,
            "kubernetes_spend_inr": kube_total,
            "ai_spend_inr": ai_total,
            "invoice_total_inr": invoice_total,
            "forecast_total_inr": forecast_total,
            "tokens": tokens,
            "requests": requests,
            "gpu_hours": round(gpu_seconds / 3600, 1),
            "active_customers": len(customers),
        },
        "customers": [
            {"id": c.id, "name": c.name, "segment": c.segment, "region": c.region, "billing_model": c.billing_model, "status": c.status}
            for c in customers
        ],
        "cloudProviders": [{"name": row[0], "amount": money(row[1])} for row in provider_rows],
        "cloudIntegrations": [cloud_integration_payload(row) for row in cloud_integrations_rows],
        "aiProviders": [{"name": row[0], "amount": money(row[1]), "tokens": money(row[2]), "requests": money(row[3])} for row in ai_rows],
        "teamChargeback": [{"team": team, "amount": money(amount)} for team, amount in sorted(chargeback.items(), key=lambda x: x[1], reverse=True)],
        "kubernetes": [
            {
                "cluster": n.cluster,
                "namespace": n.namespace,
                "workload": n.workload,
                "team": n.team,
                "cpu": n.cpu_core_hours,
                "memory": n.memory_gb_hours,
                "gpu": n.gpu_hours,
                "amount": money(n.amount_inr),
                "source": "live" if is_live_snapshot_row(n) else "demo",
            }
            for n in namespaces
        ],
        "aiUsage": [
            {
                "provider": a.provider,
                "model": a.model,
                "product": a.product,
                "tokens": a.tokens,
                "requests": a.requests,
                "gpuSeconds": a.gpu_seconds,
                "storageGb": a.storage_gb,
                "documents": a.documents,
                "amount": money(a.amount_inr),
            }
            for a in ai_usage
        ],
        "networkUsage": [
            {
                "cluster": n.cluster,
                "namespace": n.namespace,
                "workload": n.workload,
                "rxBytesPerSec": round(n.rx_bytes_per_sec, 2),
                "txBytesPerSec": round(n.tx_bytes_per_sec, 2),
                "connections": n.connections,
                "source": n.source,
                "observedAt": n.observed_at.isoformat(),
            }
            for n in network_usage
        ],
        "nodeInventory": [
            {
                "cluster": n.cluster,
                "nodeName": n.node_name,
                "instanceType": n.instance_type,
                "zone": n.zone,
                "providerId": n.provider_id,
                "cpuAllocatable": n.cpu_allocatable,
                "memoryGib": n.memory_gib,
                "hourlyInr": n.hourly_inr,
                "monthlyInr": money(n.hourly_inr * 730),
                "source": n.source,
                "observedAt": n.observed_at.isoformat(),
            }
            for n in node_inventory
        ],
        "invoices": [
            {
                "invoiceNo": i.invoice_no,
                "customerId": i.customer_id,
                "issueDate": i.issue_date.isoformat(),
                "status": i.status,
                "cloud": money(i.cloud_amount_inr),
                "kubernetes": money(i.kubernetes_amount_inr),
                "ai": money(i.ai_amount_inr),
                "tax": money(i.tax_inr),
                "total": money(i.total_inr),
            }
            for i in invoices
        ],
        "alerts": [
            {
                "scope": a.scope,
                "owner": a.owner,
                "threshold": money(a.threshold_inr),
                "current": money(a.current_inr),
                "severity": a.severity,
                "message": a.message,
            }
            for a in alerts
        ],
        "recommendations": [
            "Move steady GPU inference from on-demand cloud GPUs to reserved capacity for MedLM Labs.",
            "Create namespace budgets for payments, risk-engine, tenant-alpha, and tenant-beta.",
            "Bill AI products by blended token, request, document, storage, and GPU dimensions.",
            "Use MSP invoice splits to pass through AWS, OCI, GCP, Kubernetes, and AI line items cleanly.",
        ],
        "teamCost": [{"team": team, "amount": money(amount)} for team, amount in sorted(kubernetes_team_cost.items(), key=lambda x: x[1], reverse=True)],
    }
