import json
import sys

from rich.console import Console
from rich.table import Table

from app.models import Transaction
from app.money import fmt

# Docker logs and pipes aren't terminals; give tables room instead of wrapping at 80 columns.
console = Console(highlight=False, width=None if sys.stdout.isatty() else 130)

STYLE = {
    "executed": ("APPROVED", "bold green"), "approved": ("APPROVED", "bold green"),
    "pending_confirmation": ("NEEDS CONFIRMATION", "bold yellow"),
    "rejected": ("REJECTED", "bold red"), "denied": ("DENIED", "red"),
    "expired": ("EXPIRED", "dim"), "failed": ("PAYMENT FAILED", "red"),
}


def label(status: str) -> str:
    text, style = STYLE.get(status, (status.upper(), "white"))
    return f"[{style}]{text}[/]"


def tx_line(tx: Transaction) -> None:
    by = ""
    if tx.decided_by and tx.decided_by != "policy":
        verb = "confirmed" if tx.status in ("executed", "failed", "approved") else tx.status
        by = f" ({verb} by {tx.decided_by})" if verb != tx.status else f" by {tx.decided_by}"
    console.print(f"  {label(tx.status)}{by}  {tx.merchant}: {tx.description}, "
                  f"[bold]{fmt(tx.amount_cents, tx.currency)}[/]")
    console.print(f"  [dim]{tx.rule}: {tx.reason}[/]")
    if tx.failure:
        console.print(f"  [red]wallet: {tx.failure}[/]")


def tx_table(rows: list[Transaction], title: str) -> Table:
    t = Table(title=title, title_justify="left")
    for col in ("id", "when (UTC)", "merchant", "amount", "status", "rule"):
        t.add_column(col, justify="right" if col == "amount" else "left")
    for tx in rows:
        t.add_row(tx.id[:8], f"{tx.created_at:%Y-%m-%d %H:%M}", tx.merchant, fmt(tx.amount_cents, tx.currency),
                  label(tx.status), tx.rule)
    return t


def audit_table(entries, title: str) -> Table:
    t = Table(title=title, title_justify="left")
    for col in ("#", "time (UTC)", "event", "actor", "tx", "details", "hash"):
        t.add_column(col)
    for e in entries:
        data = json.loads(e.data)
        detail = data.get("amount") or data.get("rule") or data.get("error") or data.get("note") or ""
        t.add_row(str(e.seq), f"{e.ts:%Y-%m-%d %H:%M:%S}", e.event, e.actor, (e.transaction_id or "")[:8],
                  str(detail)[:40], e.hash[:10])
    return t
