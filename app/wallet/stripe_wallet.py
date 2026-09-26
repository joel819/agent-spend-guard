"""Stripe in TEST mode: every approved transaction becomes a confirmed PaymentIntent paid with a
Stripe test card. Live keys are refused, so this can't move real money."""
import stripe

from app.wallet.base import PaymentDeclined, WalletConfigError

TEST_CARD = "pm_card_visa"
DECLINING_CARD = "pm_card_chargeDeclined"


class StripeWallet:
    name = "stripe-test"

    def __init__(self, secret_key: str):
        if not secret_key.startswith(("sk_test_", "rk_test_")):
            raise WalletConfigError("Only Stripe TEST keys (sk_test_...) are allowed. Refusing to use a live key.")
        self.client = stripe.StripeClient(secret_key)

    def balance_cents(self) -> int | None:
        return None  # a card has no balance; the daily cap is the budget

    def charge(self, tx_id: str, amount_cents: int, currency: str, merchant: str, description: str) -> str:
        card = DECLINING_CARD if "[decline]" in description.lower() else TEST_CARD
        try:
            pi = self.client.v1.payment_intents.create(
                params={
                    "amount": amount_cents, "currency": currency.lower(), "payment_method": card, "confirm": True,
                    "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
                    "description": f"{merchant}: {description}"[:1000],
                    "metadata": {"spend_guard_tx": tx_id, "merchant": merchant[:500]},
                },
                options={"idempotency_key": f"spend-guard-{tx_id}"},
            )
        except stripe.CardError as exc:
            raise PaymentDeclined(f"card_declined: {exc.user_message or exc}") from None
        except stripe.StripeError as exc:
            raise PaymentDeclined(f"stripe_error: {exc}") from None
        if pi.status != "succeeded":
            raise PaymentDeclined(f"payment_{pi.status}")
        return pi.id
