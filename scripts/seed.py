"""Two weeks of realistic history (before today), so the audit log and transaction list aren't
empty on first start. Today is left untouched, so the full daily cap is available for the demo.
Skipped if any transactions exist.

Usage: python -m scripts.seed
"""
import random
from datetime import timedelta

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.guard import Proposal, build_guard, utcnow
from app.models import Transaction
from app.money import to_cents

CATALOGUE = [
    ("OpenAI", "software", "API usage top-up", (10, 40)),
    ("Groq Cloud", "software", "API credits", (5, 25)),
    ("AWS", "compute", "EC2 spot instances", (8, 45)),
    ("Vercel", "software", "Pro plan seat", (20, 20)),
    ("Cloudflare", "software", "Workers paid plan", (5, 5)),
    ("Namecheap", "software", "Domain renewal", (9, 15)),
    ("O'Reilly", "education", "E-book", (25, 45)),
    ("Hetzner", "compute", "VPS monthly", (12, 30)),
    ("Lambda Cloud", "compute", "GPU hours", (30, 90)),
    ("Deutsche Bahn", "travel", "Train ticket to client meeting", (39, 89)),
    ("Logitech", "hardware", "Webcam", (60, 110)),
    ("Lucky Spin Casino", "gambling", "Chips", (20, 20)),
]


def seed(days: int = 14, verbose: bool = True) -> int:
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Transaction)):
            if verbose:
                print("Transactions already exist; skipping seed.")
            return 0
    rng = random.Random(42)
    start = utcnow().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=days)
    clock = {"now": start}
    guard = build_guard(clock=lambda: clock["now"])
    n = 0
    for d in range(days):
        clock["now"] = start + timedelta(days=d)
        for _ in range(rng.randint(2, 5)):
            clock["now"] += timedelta(minutes=rng.randint(20, 150))
            merchant, cat, desc, (lo, hi) = rng.choice(CATALOGUE)
            amount = f"{rng.uniform(lo, hi):.2f}" if hi > lo else f"{lo:.2f}"
            tx = guard.propose(Proposal("research-agent", merchant, cat, desc, to_cents(amount), "EUR"))
            n += 1
            if tx.status == "pending_confirmation":
                clock["now"] += timedelta(minutes=rng.randint(2, 10))
                roll = rng.random()
                if roll < 0.65:
                    guard.confirm(tx.id, "human:ops-lead")
                elif roll < 0.9:
                    guard.deny(tx.id, "human:ops-lead", "Not needed this week")
                # else: nobody answers; it expires on the next guard call
    if verbose:
        print(f"Seeded {n} transactions over {days} days (today untouched).")
    return n


if __name__ == "__main__":
    seed()
