"""Append-only, hash-chained audit log.

Each entry's hash covers its content and the previous entry's hash, so changing, deleting or
reordering any past entry breaks the chain at that point, and verify() says exactly where.
(Cutting off the newest entries isn't detectable from the log alone; anchor the head hash
somewhere external, e.g. print it daily, if that matters.)
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEntry

GENESIS = "0" * 64


def _digest(seq: int, ts: datetime, event: str, transaction_id: str | None, actor: str, data: str,
            prev_hash: str) -> str:
    payload = json.dumps([seq, ts.isoformat(), event, transaction_id, actor, data, prev_hash], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def record(db: Session, now: datetime, event: str, actor: str, data: dict[str, Any] | None = None,
           transaction_id: str | None = None) -> AuditEntry:
    """Append an entry. Call inside the same DB transaction as the change it describes."""
    last = db.scalar(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1))
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    body = json.dumps(data or {}, sort_keys=True, default=str)
    entry = AuditEntry(seq=seq, ts=now, event=event, transaction_id=transaction_id, actor=actor, data=body,
                       prev_hash=prev, hash=_digest(seq, now, event, transaction_id, actor, body, prev))
    db.add(entry)
    db.flush()
    return entry


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    head_hash: str
    problem: str | None = None
    bad_seq: int | None = None


def verify(db: Session) -> VerifyResult:
    prev, expected_seq, n = GENESIS, 1, 0
    for e in db.scalars(select(AuditEntry).order_by(AuditEntry.seq)):
        n += 1
        if e.seq != expected_seq:
            return VerifyResult(False, n, prev, f"entry {expected_seq} is missing (next found: {e.seq})", expected_seq)
        if e.prev_hash != prev:
            return VerifyResult(False, n, prev, f"entry {e.seq} doesn't link to the entry before it", e.seq)
        if _digest(e.seq, e.ts, e.event, e.transaction_id, e.actor, e.data, e.prev_hash) != e.hash:
            return VerifyResult(False, n, prev, f"entry {e.seq} was modified after it was written", e.seq)
        prev, expected_seq = e.hash, expected_seq + 1
    return VerifyResult(True, n, prev)
