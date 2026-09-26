from app.config import get_settings
from app.wallet.base import PaymentDeclined, Wallet, WalletConfigError

_wallet: Wallet | None = None


def get_wallet() -> Wallet:
    """Stripe test mode when STRIPE_SECRET_KEY is set, otherwise the mock wallet."""
    global _wallet
    if _wallet is None:
        s = get_settings()
        if s.stripe_secret_key:
            from app.wallet.stripe_wallet import StripeWallet

            _wallet = StripeWallet(s.stripe_secret_key)
        else:
            from app.db import SessionLocal
            from app.wallet.mock_wallet import MockWallet

            _wallet = MockWallet(SessionLocal)
    return _wallet


def set_wallet(wallet: Wallet | None) -> None:
    global _wallet
    _wallet = wallet


__all__ = ["PaymentDeclined", "Wallet", "WalletConfigError", "get_wallet", "set_wallet"]
