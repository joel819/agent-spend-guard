import pytest

from app.wallet.base import PaymentDeclined, WalletConfigError
from app.wallet.stripe_wallet import StripeWallet


def test_mock_charge_and_balance(guard, wallet):
    assert wallet.balance_cents() == 100000
    ref = wallet.charge("tx1", 1234, "EUR", "Acme", "thing")
    assert ref == "mock_pay_tx1" and wallet.balance_cents() == 100000 - 1234


@pytest.mark.parametrize("amount,currency,desc,err", [
    (1, "EUR", "[decline] x", "card_declined"),
    (1, "USD", "x", "currency_mismatch"),
    (10_000_000, "EUR", "x", "insufficient_funds"),
])
def test_mock_declines(guard, wallet, amount, currency, desc, err):
    with pytest.raises(PaymentDeclined, match=err):
        wallet.charge("tx", amount, currency, "Acme", desc)
    assert wallet.balance_cents() == 100000


@pytest.mark.parametrize("key", ["sk_live_abc", "rk_live_abc", "pk_test_abc", "whatever"])
def test_stripe_refuses_non_test_keys(key):
    with pytest.raises(WalletConfigError, match="TEST keys"):
        StripeWallet(key)


def test_stripe_charge_uses_test_card_and_idempotency(monkeypatch):
    w = StripeWallet("sk_test_dummy")
    calls = {}

    def create(params, options):
        calls.update(params=params, options=options)
        return type("PI", (), {"id": "pi_123", "status": "succeeded"})()

    monkeypatch.setattr(w.client.v1.payment_intents, "create", create)
    assert w.charge("tx9", 2000, "EUR", "Acme", "credits") == "pi_123"
    assert calls["params"]["payment_method"] == "pm_card_visa" and calls["params"]["amount"] == 2000
    assert calls["params"]["currency"] == "eur" and calls["options"]["idempotency_key"] == "spend-guard-tx9"


def test_stripe_card_error_becomes_decline(monkeypatch):
    import stripe

    w = StripeWallet("sk_test_dummy")

    def create(params, options):
        raise stripe.CardError("Your card was declined.", None, "card_declined")

    monkeypatch.setattr(w.client.v1.payment_intents, "create", create)
    with pytest.raises(PaymentDeclined, match="card_declined"):
        w.charge("tx", 100, "EUR", "Acme", "x")
