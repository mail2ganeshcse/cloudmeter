from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    segment: Mapped[str] = mapped_column(String(80))
    region: Mapped[str] = mapped_column(String(80))
    billing_model: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="active")


class CloudSpend(Base):
    __tablename__ = "cloud_spend"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    service: Mapped[str] = mapped_column(String(80))
    team: Mapped[str] = mapped_column(String(80))
    amount_inr: Mapped[float] = mapped_column(Float)
    month: Mapped[str] = mapped_column(String(7), index=True)


class KubernetesCost(Base):
    __tablename__ = "kubernetes_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    cluster: Mapped[str] = mapped_column(String(80))
    namespace: Mapped[str] = mapped_column(String(80))
    workload: Mapped[str] = mapped_column(String(120))
    team: Mapped[str] = mapped_column(String(80))
    cpu_core_hours: Mapped[float] = mapped_column(Float)
    memory_gb_hours: Mapped[float] = mapped_column(Float)
    gpu_hours: Mapped[float] = mapped_column(Float)
    amount_inr: Mapped[float] = mapped_column(Float)
    month: Mapped[str] = mapped_column(String(7), index=True)


class NetworkUsage(Base):
    __tablename__ = "network_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    cluster: Mapped[str] = mapped_column(String(120), index=True)
    namespace: Mapped[str] = mapped_column(String(80))
    workload: Mapped[str] = mapped_column(String(120))
    rx_bytes_per_sec: Mapped[float] = mapped_column(Float)
    tx_bytes_per_sec: Mapped[float] = mapped_column(Float)
    connections: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(80), default="inventory")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    product: Mapped[str] = mapped_column(String(80))
    tokens: Mapped[int] = mapped_column(Integer)
    requests: Mapped[int] = mapped_column(Integer)
    gpu_seconds: Mapped[int] = mapped_column(Integer)
    storage_gb: Mapped[float] = mapped_column(Float)
    documents: Mapped[int] = mapped_column(Integer)
    amount_inr: Mapped[float] = mapped_column(Float)
    month: Mapped[str] = mapped_column(String(7), index=True)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    invoice_no: Mapped[str] = mapped_column(String(40), unique=True)
    issue_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40))
    cloud_amount_inr: Mapped[float] = mapped_column(Float)
    kubernetes_amount_inr: Mapped[float] = mapped_column(Float)
    ai_amount_inr: Mapped[float] = mapped_column(Float)
    tax_inr: Mapped[float] = mapped_column(Float)
    total_inr: Mapped[float] = mapped_column(Float)


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    scope: Mapped[str] = mapped_column(String(80))
    owner: Mapped[str] = mapped_column(String(80))
    threshold_inr: Mapped[float] = mapped_column(Float)
    current_inr: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String(240))


class ClusterConnection(Base):
    __tablename__ = "cluster_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    cluster_name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40))
    environment: Mapped[str] = mapped_column(String(40))
    token: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    agent_mode: Mapped[str] = mapped_column(String(40), default="read-only")
    last_seen: Mapped[str] = mapped_column(String(80), default="Waiting for agent")


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    github_sub: Mapped[str] = mapped_column(String(120), default="", index=True)
    sso_sub: Mapped[str] = mapped_column(String(180), default="", index=True)
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(140))
    avatar: Mapped[str] = mapped_column(String(400), default="")
    username: Mapped[str] = mapped_column(String(180), default="")
    password_salt: Mapped[str] = mapped_column(String(80), default="")
    password_hash: Mapped[str] = mapped_column(String(160), default="")
    first_name: Mapped[str] = mapped_column(String(80), default="")
    last_name: Mapped[str] = mapped_column(String(80), default="")
    country_code: Mapped[str] = mapped_column(String(12), default="+91")
    phone_number: Mapped[str] = mapped_column(String(40), default="")
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(40), default="viewer")
    provider: Mapped[str] = mapped_column(String(40), default="google")
    hosted_domain: Mapped[str] = mapped_column(String(160), default="")
    first_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
