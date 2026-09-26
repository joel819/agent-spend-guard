"""The gatekeeper. Every proposed transaction passes through here.

Flow for one proposal:
  1. In one BEGIN IMMEDIATE transaction: expire stale holds, sum today's usage, evaluate the
     policy, insert the transaction (approved / pending_confirmation / rejected), audit it.
     Holding the write lock makes check-and-reserve atomic: parallel proposals queue up.
  2. If approved: charge the wallet *outside* the lock (it may be a network call).
  3. In a second transaction: mark executed or failed (a failed charge releases its hold).

Pending confirmations hold their amount against the daily cap until confirmed, denied or expired.
"""
import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.models import Transaction, WalletAccount
from app.money import fmt
from app.policy.engine import evaluate
from app.policy.loader import Policy
from app.wallet.base import PaymentDeclined, Wallet

# Statuses that count against the daily cap
HOLDS = ("approved", "executed", "pending_confirmation")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GuardError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Proposal:
    agent: str
    merchant: str
    category: str
    description: str
    amount_cents: int
    currency: str
    idempotency_key: str | None = None

    def fingerprint(self) -> str:
        body = [self.agent, self.merchant, self.category.lower(), self.description, self.amount_cents, self.currency]
        return hashlib.sha256(json.dumps(body).encode()).hexdigest()


class Guard:
    def __init__(self, sessions: Callable[[], Session], policy: Policy, wallet: Wallet,
                 clock: Callable[[], datetime] = utcnow):
        self.sessions = sessions
        self.policy = policy
        self.wallet = wallet
        self.clock = clock

    # ---------- helpers ----------

    def day_of(self, ts: datetime) -> str:
        return ts.replace(tzinfo=UTC).astimezone(self.policy.tz).date().isoformat()

    def used_today(self, db: Session, now: datetime, exclude_id: str | None = None) -> int:
        q = select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.day == self.day_of(now), Transaction.status.in_(HOLDS))
        if exclude_id:
            q = q.where(Transaction.id != exclude_id)
        return int(db.scalar(q))

    def _expire_stale(self, db: Session, now: datetime) -> None:
        stale = db.scalars(select(Transaction).where(
            Transaction.status == "pending_confirmation", Transaction.expires_at <= now)).all()
        for tx in stale:
            tx.status, tx.decided_by, tx.decided_at = "expired", "system", now
            audit.record(db, now, "expired", "system", {"amount": fmt(tx.amount_cents, tx.currency),
                                                          "hold_released": True}, tx.id)

    def summary(self) -> dict:
        now = self.clock()
        with self.sessions() as db, db.begin():
            self._expire_stale(db, now)
            used = self.used_today(db, now)
            pending = db.scalar(select(func.count()).where(Transaction.status == "pending_confirmation"))
        p = self.policy
        return {"day": self.day_of(now), "currency": p.currency, "used_today_cents": used,
                "remaining_today_cents": max(0, p.daily_cap_cents - used), "pending_confirmations": pending,
                "per_transaction_cap_cents": p.per_transaction_cap_cents, "daily_cap_cents": p.daily_cap_cents,
                "balance_cents": self.wallet.balance_cents(), "wallet": self.wallet.name}

    # ---------- propose ----------

    def propose(self, p: Proposal) -> Transaction:
        now = self.clock()
        with self.sessions() as db, db.begin():
            if p.idempotency_key:
                existing = db.scalar(select(Transaction).where(Transaction.idempotency_key == p.idempotency_key))
                if existing:
                    if existing.request_fingerprint != p.fingerprint():
                        raise GuardError(409, "idempotency_conflict",
                                         "This Idempotency-Key was already used for a different transaction.")
                    return existing  # retry of the same request: same result, no second decision
            self._expire_stale(db, now)
            used = self.used_today(db, now)
            ev = evaluate(p.amount_cents, p.currency, p.category, used, self.policy)
            status = {"approve": "approved", "confirm": "pending_confirmation", "reject": "rejected"}[ev.outcome]
            tx = Transaction(
                id=uuid.uuid4().hex, created_at=now, day=self.day_of(now), agent=p.agent, merchant=p.merchant,
                category=p.category.lower(), description=p.description, amount_cents=p.amount_cents,
                currency=p.currency, status=status, decision=ev.outcome, rule=ev.rule, reason=ev.reason,
                policy_fingerprint=self.policy.fingerprint, idempotency_key=p.idempotency_key,
                request_fingerprint=p.fingerprint(),
                expires_at=now + timedelta(minutes=self.policy.confirmation_timeout_minutes)
                if ev.outcome == "confirm" else None,
                decided_by="policy" if ev.outcome != "confirm" else None,
                decided_at=now if ev.outcome != "confirm" else None,
            )
            db.add(tx)
            db.flush()
            data = {"merchant": p.merchant, "category": tx.category, "amount": fmt(p.amount_cents, p.currency),
                    "description": p.description, "used_before": fmt(used, self.policy.currency),
                    "rule": ev.rule, "reason": ev.reason, "policy": self.policy.fingerprint}
            audit.record(db, now, "proposed", p.agent, data, tx.id)
            event = {"approve": "auto_approved", "confirm": "confirmation_required", "reject": "rejected"}[ev.outcome]
            audit.record(db, now, event, "policy", {"rule": ev.rule, "reason": ev.reason}, tx.id)
        if tx.status == "approved":
            tx = self._execute(tx.id)
        return tx

    # ---------- human decisions ----------

    def confirm(self, tx_id: str, approver: str) -> Transaction:
        now = self.clock()
        with self.sessions() as db, db.begin():
            self._expire_stale(db, now)
            tx = self._pending(db, tx_id)
            # Re-check the daily cap: the policy may have changed since the hold was placed.
            used_other = self.used_today(db, now, exclude_id=tx.id)
            if used_other + tx.amount_cents > self.policy.daily_cap_cents:
                tx.status, tx.decided_by, tx.decided_at = "rejected", "policy", now
                tx.rule, tx.reason = "daily_cap", (
                    f"Confirmation came too late: approving it now would exceed the daily cap of "
                    f"{fmt(self.policy.daily_cap_cents, tx.currency)}.")
                audit.record(db, now, "rejected", "policy", {"rule": "daily_cap", "at": "confirmation"}, tx.id)
                return tx
            tx.status, tx.decided_by, tx.decided_at = "approved", approver, now
            audit.record(db, now, "confirmed", approver, {"amount": fmt(tx.amount_cents, tx.currency)}, tx.id)
        return self._execute(tx_id)

    def deny(self, tx_id: str, approver: str, note: str = "") -> Transaction:
        now = self.clock()
        with self.sessions() as db, db.begin():
            self._expire_stale(db, now)
            tx = self._pending(db, tx_id)
            tx.status, tx.decided_by, tx.decided_at = "denied", approver, now
            audit.record(db, now, "denied", approver, {"note": note[:500], "hold_released": True}, tx.id)
        return tx

    def _pending(self, db: Session, tx_id: str) -> Transaction:
        tx = db.get(Transaction, tx_id)
        if tx is None:
            raise GuardError(404, "not_found", f"No transaction {tx_id}.")
        if tx.status != "pending_confirmation":
            raise GuardError(409, "not_pending",
                             f"Transaction {tx_id} is '{tx.status}', not waiting for confirmation.")
        return tx

    # ---------- money movement ----------

    def _execute(self, tx_id: str) -> Transaction:
        with self.sessions() as db:
            tx = db.get(Transaction, tx_id)
        try:
            ref, failure = self.wallet.charge(tx.id, tx.amount_cents, tx.currency, tx.merchant, tx.description), None
        except PaymentDeclined as exc:
            ref, failure = None, str(exc)
        now = self.clock()
        with self.sessions() as db, db.begin():
            # Conditional update: only an 'approved' transaction can be finalised, exactly once.
            new_status = "executed" if ref else "failed"
            done = db.execute(update(Transaction).where(Transaction.id == tx_id, Transaction.status == "approved")
                              .values(status=new_status, payment_ref=ref, failure=failure))
            if done.rowcount:
                if ref:
                    audit.record(db, now, "executed", f"wallet:{self.wallet.name}",
                                 {"payment_ref": ref, "amount": fmt(tx.amount_cents, tx.currency)}, tx_id)
                else:
                    audit.record(db, now, "payment_failed", f"wallet:{self.wallet.name}",
                                 {"error": failure, "hold_released": True}, tx_id)
            return db.get(Transaction, tx_id)


# ---------- process-wide instance ----------

_guard: Guard | None = None


def build_guard(sessions=None, policy: Policy | None = None, wallet: Wallet | None = None,
                clock: Callable[[], datetime] = utcnow) -> Guard:
    from app.config import get_settings
    from app.db import SessionLocal
    from app.money import to_cents
    from app.policy.loader import get_policy
    from app.wallet import get_wallet
    from app.wallet.mock_wallet import MockWallet

    sessions = sessions or SessionLocal
    policy = policy or get_policy()
    wallet = wallet or get_wallet()
    if isinstance(wallet, MockWallet):
        with sessions() as db, db.begin():
            if db.get(WalletAccount, 1) is None:
                wallet.ensure(db, policy.currency, to_cents(get_settings().opening_balance))
                audit.record(db, clock(), "wallet_opened", "system",
                             {"balance": get_settings().opening_balance, "currency": policy.currency})
    return Guard(sessions, policy, wallet, clock)


def get_guard() -> Guard:
    global _guard
    if _guard is None:
        _guard = build_guard()
    return _guard


def set_guard(guard: Guard | None) -> None:
    global _guard
    _guard = guard
