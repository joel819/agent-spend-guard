"""What an agent sees when it proposes a payment: the guard's decision, and for anything over the
cap, the outcome of the human confirmation. Agents can propose; they can never approve."""
from collections.abc import Callable
from dataclasses import dataclass, field

from app.guard import Guard, Proposal
from app.models import Transaction
from app.money import to_cents

# Called when a transaction needs a human. Returns True (confirm) or False (deny).
ConfirmFn = Callable[[Transaction], bool]
# Optional hooks for showing progress: before a proposal, and after its final outcome.
BeforeFn = Callable[[str, "Purchase"], None]
AfterFn = Callable[[Transaction], None]


@dataclass
class Purchase:
    merchant: str
    category: str
    description: str
    amount: str
    currency: str = "EUR"


@dataclass
class RunLog:
    steps: list[tuple[Purchase, Transaction]] = field(default_factory=list)


def submit(guard: Guard, agent: str, item: Purchase, confirm: ConfirmFn, log: RunLog,
           before: BeforeFn | None = None, after: AfterFn | None = None) -> Transaction:
    if before:
        before(agent, item)
    tx = guard.propose(Proposal(agent=agent, merchant=item.merchant, category=item.category,
                                description=item.description, amount_cents=to_cents(item.amount),
                                currency=item.currency))
    if tx.status == "pending_confirmation":
        tx = guard.confirm(tx.id, "human:cli") if confirm(tx) else guard.deny(tx.id, "human:cli")
    log.steps.append((item, tx))
    if after:
        after(tx)
    return tx
