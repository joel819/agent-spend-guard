import json

from sqlalchemy import select, text

from app import audit
from app.models import AuditEntry


def events(sessions, tx_id=None):
    with sessions() as db:
        q = select(AuditEntry).order_by(AuditEntry.seq)
        if tx_id:
            q = q.where(AuditEntry.transaction_id == tx_id)
        return [e.event for e in db.scalars(q)]


def test_every_path_is_logged(guard, propose, sessions, clock):
    from datetime import timedelta

    a = propose("10.00")
    b = propose("120.00")
    guard.confirm(b.id, "human:alice")
    c = propose("60.00")
    guard.deny(c.id, "human:alice", "no")
    d = propose("90.00")
    e = propose("45.00", description="[decline]")
    f = propose("70.00")  # 10 + 120 + 45(failed, released) ... used 130 -> pending
    clock.now += timedelta(minutes=20)
    guard.summary()
    assert events(sessions, a.id) == ["proposed", "auto_approved", "executed"]
    assert events(sessions, b.id) == ["proposed", "confirmation_required", "confirmed", "executed"]
    assert events(sessions, c.id) == ["proposed", "confirmation_required", "denied"]
    assert events(sessions, d.id) == ["proposed", "rejected"]
    assert events(sessions, e.id) == ["proposed", "auto_approved", "payment_failed"]
    assert events(sessions, f.id) == ["proposed", "confirmation_required", "expired"]
    assert events(sessions)[0] == "wallet_opened"


def test_audit_records_who_and_why(guard, propose, sessions):
    tx = propose("120.00")
    guard.confirm(tx.id, "human:alice")
    with sessions() as db:
        rows = db.scalars(select(AuditEntry).where(AuditEntry.transaction_id == tx.id).order_by(AuditEntry.seq)).all()
    assert rows[0].actor == "test-agent" and json.loads(rows[0].data)["amount"] == "120.00 EUR"
    assert rows[1].actor == "policy" and json.loads(rows[1].data)["rule"] == "per_transaction_cap"
    assert rows[2].actor == "human:alice"
    assert rows[3].actor == "wallet:mock" and json.loads(rows[3].data)["payment_ref"].startswith("mock_pay_")


def test_chain_verifies(guard, propose, sessions):
    for amt in ("10.00", "20.00", "120.00"):
        propose(amt)
    with sessions() as db:
        r = audit.verify(db)
    assert r.ok and r.entries == 1 + 3 + 3 + 3 - 1  # wallet_opened + events


def _tamper(sessions, sql):
    with sessions() as db, db.begin():
        db.execute(text(sql))
    with sessions() as db:
        return audit.verify(db)


def test_modified_entry_detected(guard, propose, sessions):
    propose("10.00")
    propose("20.00")
    r = _tamper(sessions, "UPDATE audit_log SET data = replace(data, '20.00', '2.00') WHERE seq = 5")
    assert not r.ok and r.bad_seq == 5 and "modified" in r.problem


def test_deleted_entry_detected(guard, propose, sessions):
    propose("10.00")
    propose("20.00")
    r = _tamper(sessions, "DELETE FROM audit_log WHERE seq = 3")
    assert not r.ok and r.bad_seq == 3 and "missing" in r.problem


def test_rehashed_entry_still_detected(guard, propose, sessions):
    """Editing an entry and recomputing its own hash breaks the link to the next entry."""
    propose("10.00")
    propose("20.00")
    with sessions() as db, db.begin():
        e = db.get(AuditEntry, 3)
        e.actor = "someone-else"
        e.hash = audit._digest(e.seq, e.ts, e.event, e.transaction_id, e.actor, e.data, e.prev_hash)
    with sessions() as db:
        r = audit.verify(db)
    assert not r.ok and r.bad_seq == 4
