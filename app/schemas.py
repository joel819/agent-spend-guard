from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models import Transaction
from app.money import from_cents


class ProposeIn(BaseModel):
    agent: str = Field(min_length=1, max_length=80, description="Which agent is asking")
    merchant: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, description="e.g. 12.50")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    idempotency_key: str | None = Field(default=None, max_length=120)

    @field_validator("category")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class DecisionIn(BaseModel):
    approver: str = Field(min_length=1, max_length=80, description="Who is deciding (recorded in the audit log)")
    note: str = Field(default="", max_length=500)


class TransactionOut(BaseModel):
    id: str
    created_at: datetime
    agent: str
    merchant: str
    category: str
    description: str
    amount: str
    currency: str
    status: str
    decision: str
    rule: str
    reason: str
    expires_at: datetime | None
    decided_by: str | None
    payment_ref: str | None
    failure: str | None

    @classmethod
    def of(cls, tx: Transaction) -> "TransactionOut":
        return cls(**{k: getattr(tx, k) for k in cls.model_fields if k != "amount"},
                   amount=f"{from_cents(tx.amount_cents)}")


class AuditOut(BaseModel):
    seq: int
    ts: datetime
    event: str
    transaction_id: str | None
    actor: str
    data: dict[str, Any]
    hash: str
