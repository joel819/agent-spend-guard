import json

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import audit
from app.guard import get_guard
from app.models import AuditEntry
from app.schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(transaction_id: str | None = None, event: str | None = None, limit: int = Query(100, ge=1, le=1000)):
    q = select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(limit)
    if transaction_id:
        q = q.where(AuditEntry.transaction_id == transaction_id)
    if event:
        q = q.where(AuditEntry.event == event)
    with get_guard().sessions() as db:
        return [AuditOut(seq=e.seq, ts=e.ts, event=e.event, transaction_id=e.transaction_id, actor=e.actor,
                         data=json.loads(e.data), hash=e.hash) for e in db.scalars(q)]


@router.get("/verify")
def verify() -> dict:
    with get_guard().sessions() as db:
        r = audit.verify(db)
    return {"ok": r.ok, "entries_checked": r.entries, "head_hash": r.head_hash, "problem": r.problem,
            "bad_seq": r.bad_seq}
