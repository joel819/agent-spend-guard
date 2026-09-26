"""The decision rule, as a pure function: no database, no clock, no I/O. Easy to test exhaustively.

Order matters. Rejections come first, so no confirmation can ever unlock something the
policy forbids outright.
"""
from dataclasses import dataclass
from typing import Literal

from app.money import fmt
from app.policy.loader import Policy

Outcome = Literal["approve", "confirm", "reject"]


@dataclass(frozen=True)
class Evaluation:
    outcome: Outcome
    rule: str
    reason: str


def evaluate(amount_cents: int, currency: str, category: str, used_today_cents: int, policy: Policy) -> Evaluation:
    cur = policy.currency
    if currency != cur:
        return Evaluation("reject", "currency_mismatch",
                          f"Wallet and caps are in {cur}; this transaction is in {currency}.")
    if category.lower() in policy.blocked_categories:
        return Evaluation("reject", "blocked_category", f"Category '{category}' is blocked by policy.")
    after = used_today_cents + amount_cents
    if after > policy.daily_cap_cents:
        return Evaluation(
            "reject", "daily_cap",
            f"{fmt(amount_cents, cur)} would bring today's spend to {fmt(after, cur)}, over the daily cap of "
            f"{fmt(policy.daily_cap_cents, cur)} ({fmt(policy.daily_cap_cents - used_today_cents, cur)} left today). "
            "The daily cap cannot be overridden.")
    if amount_cents > policy.per_transaction_cap_cents:
        return Evaluation(
            "confirm", "per_transaction_cap",
            f"{fmt(amount_cents, cur)} is over the per-transaction cap of "
            f"{fmt(policy.per_transaction_cap_cents, cur)}; a human must confirm it.")
    if category.lower() in policy.always_confirm_categories:
        return Evaluation("confirm", "always_confirm_category",
                          f"Category '{category}' always requires human confirmation.")
    return Evaluation("approve", "within_caps",
                      f"{fmt(amount_cents, cur)} is within the per-transaction cap; "
                      f"{fmt(policy.daily_cap_cents - after, cur)} left today.")
