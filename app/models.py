from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


from app.db import Base


class WalletAccount(Base):
    """Mock wallet balance (the Stripe wallet doesn't use it)."""

    __tablename__ = "wallet"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    balance_cents: Mapped[int] = mapped_column(Integer)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD in the policy timezone
    agent: Mapped[str] = mapped_column(String(80))
    merchant: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(500))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    # approved (charging now) | executed | pending_confirmation | rejected | denied | expired | failed
    status: Mapped[str] = mapped_column(String(24), index=True)
    decision: Mapped[str] = mapped_column(String(10))  # approve | confirm | reject
    rule: Mapped[str] = mapped_column(String(40))  # which policy rule decided it
    reason: Mapped[str] = mapped_column(Text)
    policy_fingerprint: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    payment_ref: Mapped[str | None] = mapped_column(String(80))
    failure: Mapped[str | None] = mapped_column(Text)


class AuditEntry(Base):
    """Append-only, hash-chained: hash = sha256(prev_hash + this entry's content)."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    event: Mapped[str] = mapped_column(String(40), index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    data: Mapped[str] = mapped_column(Text)  # JSON
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
