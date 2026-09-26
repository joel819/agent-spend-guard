import pytest

from app.money import to_cents
from app.policy.engine import evaluate
from app.policy.loader import PolicyError, parse_policy
from tests.conftest import POLICY_TOML


def ev(amount, used="0", category="software", currency="EUR", policy=None):
    return evaluate(to_cents(amount), currency, category, to_cents(used), policy or parse_policy(POLICY_TOML))


@pytest.mark.parametrize("amount,used,outcome,rule", [
    ("10.00", "0", "approve", "within_caps"),
    ("50.00", "0", "approve", "within_caps"),               # exactly at the per-transaction cap
    ("50.01", "0", "confirm", "per_transaction_cap"),       # one cent over
    ("150.00", "50.00", "confirm", "per_transaction_cap"),  # lands exactly on the daily cap
    ("40.00", "160.00", "approve", "within_caps"),          # exactly at the daily cap
    ("40.01", "160.00", "reject", "daily_cap"),             # one cent over the daily cap
    ("0.01", "200.00", "reject", "daily_cap"),
    ("250.00", "0", "reject", "daily_cap"),                 # over both: the hard limit wins
])
def test_boundaries(amount, used, outcome, rule):
    e = ev(amount, used)
    assert (e.outcome, e.rule) == (outcome, rule)


def test_reject_reason_is_explicit():
    r = ev("30.00", "181.99").reason
    assert "211.99 EUR" in r and "18.01 EUR left" in r and "cannot be overridden" in r


def test_currency_mismatch_rejected():
    assert ev("1.00", currency="USD").rule == "currency_mismatch"


def test_blocked_category_beats_everything():
    assert ev("1.00", category="Gambling").outcome == "reject"


def test_always_confirm_category_even_when_small():
    assert (ev("5.00", category="travel").outcome, ev("5.00", category="travel").rule) == (
        "confirm", "always_confirm_category")


def test_daily_cap_beats_always_confirm():
    assert ev("5.00", used="199.00", category="travel").outcome == "reject"


@pytest.mark.parametrize("bad,msg", [
    ("not toml [", "not valid TOML"),
    ('[limits]\ncurrency = "EUR"', "missing"),
    (POLICY_TOML.replace('"50.00"', '"500.00"'), "larger than daily_cap"),
    (POLICY_TOML.replace('"50.00"', '"12.345"'), "invalid"),
    (POLICY_TOML.replace('"UTC"', '"Mars/Olympus"'), "unknown timezone"),
    (POLICY_TOML.replace('"EUR"', '"euro"'), "invalid"),
    (POLICY_TOML.replace('always_confirm = ["travel"]', 'always_confirm = ["gambling"]'), "both blocked"),
])
def test_bad_policy_refuses_to_load(bad, msg):
    with pytest.raises(PolicyError, match=msg):
        parse_policy(bad)


def test_fingerprint_changes_with_policy():
    assert parse_policy(POLICY_TOML).fingerprint != parse_policy(POLICY_TOML.replace("200.00", "300.00")).fingerprint


def test_shipped_policy_file_is_valid():
    from app.config import ROOT
    from app.policy.loader import load_policy

    p = load_policy(ROOT / "spend_policy.toml")
    assert p.per_transaction_cap_cents == 5000 and p.daily_cap_cents == 20000
