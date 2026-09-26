from datetime import timedelta

import pytest

from app.guard import GuardError


def test_three_outcomes(propose):
    assert propose("20.00").status == "executed"
    assert propose("149.00").status == "pending_confirmation"
    assert propose("40.00").status == "rejected"  # 20 + 149 held + 40 > 200


def test_pending_hold_counts_toward_daily_cap(guard, propose):
    """Otherwise an agent could queue up many over-cap payments and get them all confirmed."""
    a = propose("150.00")
    b = propose("60.00")
    assert a.status == "pending_confirmation" and b.status == "rejected"
    assert guard.summary()["used_today_cents"] == 15000


def test_confirm_executes_and_charges(guard, propose, wallet):
    tx = propose("120.00")
    done = guard.confirm(tx.id, "human:alice")
    assert done.status == "executed" and done.decided_by == "human:alice" and done.payment_ref
    assert wallet.balance_cents() == 100000 - 12000


def test_deny_releases_hold(guard, propose):
    tx = propose("150.00")
    guard.deny(tx.id, "human:alice", "not now")
    assert propose("150.00").status == "pending_confirmation"  # capacity is back


def test_cannot_confirm_twice_or_confirm_non_pending(guard, propose):
    tx = propose("120.00")
    guard.confirm(tx.id, "human:a")
    with pytest.raises(GuardError, match="not waiting"):
        guard.confirm(tx.id, "human:a")
    with pytest.raises(GuardError, match="not waiting"):
        guard.deny(propose("5.00").id, "human:a")
    with pytest.raises(GuardError) as exc:
        guard.confirm("nope", "human:a")
    assert exc.value.status == 404


def test_pending_expires_and_releases_hold(guard, propose, clock):
    tx = propose("150.00")
    clock.now += timedelta(minutes=16)
    assert guard.summary()["used_today_cents"] == 0
    with pytest.raises(GuardError, match="'expired'"):
        guard.confirm(tx.id, "human:late")


def test_confirm_rechecks_daily_cap_against_new_policy(sessions, wallet, clock, propose, guard, policy):
    tx = propose("150.00")
    propose("30.00")  # executed: 180 used incl. the hold
    from app.guard import Guard

    stricter = Guard(sessions, policy.model_copy(update={"daily_cap_cents": 15000}), wallet, clock)
    out = stricter.confirm(tx.id, "human:a")
    assert out.status == "rejected" and "too late" in out.reason


def test_daily_cap_resets_at_midnight(propose, clock):
    propose("45.00")
    propose("45.00")
    propose("45.00")
    propose("45.00")
    assert propose("45.00").status == "rejected"
    clock.now += timedelta(days=1)
    assert propose("45.00").status == "executed"


def test_day_boundary_uses_policy_timezone(sessions, wallet, clock, policy):
    from app.guard import Guard

    g = Guard(sessions, policy.model_copy(update={"timezone": "Asia/Tokyo"}), wallet, clock)
    clock.now = clock.now.replace(hour=16)  # 16:00 UTC = 01:00 next day in Tokyo
    assert g.day_of(clock.now) == "2026-09-27"


def test_wallet_decline_releases_hold(guard, propose):
    tx = propose("45.00", description="[decline] test card")
    assert tx.status == "failed" and "card_declined" in tx.failure
    assert guard.summary()["used_today_cents"] == 0


def test_insufficient_funds(guard, propose, wallet, sessions):
    from app.models import WalletAccount

    with sessions() as db, db.begin():
        db.get(WalletAccount, 1).balance_cents = 1000
    tx = propose("20.00")
    assert tx.status == "failed" and "insufficient_funds" in tx.failure


def test_idempotency(propose):
    a = propose("20.00", key="k1")
    b = propose("20.00", key="k1")
    assert a.id == b.id
    with pytest.raises(GuardError) as exc:
        propose("21.00", key="k1")
    assert exc.value.status == 409


def test_every_decision_records_policy_fingerprint(propose, policy):
    assert propose("5.00").policy_fingerprint == policy.fingerprint
