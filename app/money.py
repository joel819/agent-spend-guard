"""Money is Decimal at the edges and integer cents in storage. Never float."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def to_cents(amount: Decimal | str | int) -> int:
    try:
        d = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError(f"not an amount: {amount!r}") from None
    if d != d.quantize(CENT):
        raise ValueError(f"{amount} has more than 2 decimal places")
    return int((d * 100).to_integral_value(ROUND_HALF_UP))


def from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENT)


def fmt(cents: int, currency: str) -> str:
    return f"{from_cents(cents):,.2f} {currency}"
