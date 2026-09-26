"""Every test gets a fresh SQLite file, the mock wallet and a controllable clock. No keys, no network."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="spend-guard-tests-")
os.environ.update(DATA_DIR=_tmp, DATABASE_URL="", SEED_ON_STARTUP="false", GROQ_API_KEY="",
                  STRIPE_SECRET_KEY="", APPROVER_TOKEN="", OPENING_BALANCE="1000.00")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import init_db, make_engine  # noqa: E402
from app.guard import Proposal, build_guard, set_guard  # noqa: E402
from app.money import to_cents  # noqa: E402
from app.policy.loader import parse_policy  # noqa: E402
from app.wallet.mock_wallet import MockWallet  # noqa: E402

POLICY_TOML = """
[limits]
currency = "EUR"
per_transaction_cap = "50.00"
daily_cap = "200.00"
timezone = "UTC"
[confirmation]
timeout_minutes = 15
[categories]
blocked = ["gambling"]
always_confirm = ["travel"]
"""


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 26, 10, 0, 0)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def policy():
    return parse_policy(POLICY_TOML)


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    init_db(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def wallet(sessions):
    return MockWallet(sessions)


@pytest.fixture
def guard(sessions, policy, wallet, clock):
    g = build_guard(sessions=sessions, policy=policy, wallet=wallet, clock=clock)
    set_guard(g)
    yield g
    set_guard(None)


@pytest.fixture
def propose(guard):
    def _p(amount: str, category: str = "software", merchant: str = "Acme", description: str = "thing",
           key: str | None = None, currency: str = "EUR", agent: str = "test-agent"):
        return guard.propose(Proposal(agent, merchant, category, description, to_cents(amount), currency, key))

    return _p
