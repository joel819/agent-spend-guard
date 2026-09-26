from typing import Protocol


class PaymentDeclined(Exception):
    """The wallet refused the charge (insufficient funds, card declined, ...)."""


class WalletConfigError(Exception):
    pass


class Wallet(Protocol):
    name: str

    def balance_cents(self) -> int | None:
        """Available balance, or None if the wallet has no balance concept (Stripe)."""
        ...

    def charge(self, tx_id: str, amount_cents: int, currency: str, merchant: str, description: str) -> str:
        """Move the money. Returns a payment reference. Raises PaymentDeclined."""
        ...
