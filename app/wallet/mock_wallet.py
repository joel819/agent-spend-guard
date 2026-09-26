"""SQLite-backed mock wallet. Put "[decline]" in a description to simulate a card decline."""
from sqlalchemy.orm import Session, sessionmaker

from app.models import WalletAccount
from app.money import fmt
from app.wallet.base import PaymentDeclined


class MockWallet:
    name = "mock"

    def __init__(self, session_factory: sessionmaker):
        self.sessions = session_factory

    def ensure(self, db: Session, currency: str, opening_cents: int) -> WalletAccount:
        acct = db.get(WalletAccount, 1)
        if acct is None:
            acct = WalletAccount(id=1, currency=currency, balance_cents=opening_cents)
            db.add(acct)
            db.flush()
        return acct

    def balance_cents(self) -> int | None:
        with self.sessions() as db:
            acct = db.get(WalletAccount, 1)
            return acct.balance_cents if acct else None

    def charge(self, tx_id: str, amount_cents: int, currency: str, merchant: str, description: str) -> str:
        with self.sessions() as db, db.begin():
            acct = db.get(WalletAccount, 1)
            if acct is None:
                raise PaymentDeclined("wallet_not_initialised")
            if acct.currency != currency:
                raise PaymentDeclined(f"currency_mismatch: wallet is {acct.currency}")
            if "[decline]" in description.lower():
                raise PaymentDeclined("card_declined (simulated)")
            if acct.balance_cents < amount_cents:
                raise PaymentDeclined(f"insufficient_funds: balance {fmt(acct.balance_cents, currency)}")
            acct.balance_cents -= amount_cents
        return f"mock_pay_{tx_id}"
