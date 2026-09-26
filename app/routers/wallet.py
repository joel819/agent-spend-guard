from fastapi import APIRouter

from app.guard import get_guard
from app.money import from_cents

router = APIRouter(tags=["wallet"])


def _m(cents: int | None) -> str | None:
    return None if cents is None else str(from_cents(cents))


@router.get("/wallet")
def wallet() -> dict:
    s = get_guard().summary()
    return {"wallet": s["wallet"], "currency": s["currency"], "day": s["day"], "balance": _m(s["balance_cents"]),
            "spent_or_held_today": _m(s["used_today_cents"]), "remaining_today": _m(s["remaining_today_cents"]),
            "pending_confirmations": s["pending_confirmations"]}


@router.get("/policy")
def policy() -> dict:
    p = get_guard().policy
    return {"currency": p.currency, "per_transaction_cap": _m(p.per_transaction_cap_cents),
            "daily_cap": _m(p.daily_cap_cents), "timezone": p.timezone,
            "confirmation_timeout_minutes": p.confirmation_timeout_minutes,
            "blocked_categories": sorted(p.blocked_categories),
            "always_confirm_categories": sorted(p.always_confirm_categories), "fingerprint": p.fingerprint}
