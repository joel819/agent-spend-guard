"""Operator commands on the main database (the one the API uses)."""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app import audit
from app.db import init_db
from app.guard import GuardError, Proposal, get_guard
from app.models import AuditEntry, Transaction
from app.money import fmt, to_cents
from cli.render import audit_table, console, tx_line, tx_table


def _resolve(prefix: str) -> str:
    with get_guard().sessions() as db:
        ids = db.scalars(select(Transaction.id).where(Transaction.id.startswith(prefix))).all()
    if len(ids) != 1:
        raise GuardError(404, "not_found", f"{'No' if not ids else 'More than one'} transaction matches '{prefix}'.")
    return ids[0]


def dispatch(args) -> int:
    init_db()
    guard = get_guard()
    try:
        if args.cmd == "propose":
            try:
                cents = to_cents(Decimal(args.amount))
            except (InvalidOperation, ValueError) as exc:
                console.print(f"[red]Invalid amount: {exc}[/]")
                return 2
            tx = guard.propose(Proposal(args.agent, args.merchant, args.category, args.description, cents,
                                        args.currency or guard.policy.currency))
            tx_line(tx)
            if tx.status == "pending_confirmation":
                console.print(f"  Confirm with: python -m cli confirm {tx.id[:8]}")
        elif args.cmd == "pending":
            guard.summary()  # expire stale holds first
            with get_guard().sessions() as db:
                rows = db.scalars(select(Transaction).where(Transaction.status == "pending_confirmation")
                                  .order_by(Transaction.created_at)).all()
            console.print(tx_table(rows, "Waiting for confirmation") if rows else "Nothing is waiting for confirmation.")
        elif args.cmd == "confirm":
            tx_line(guard.confirm(_resolve(args.id), f"human:{args.approver}"))
        elif args.cmd == "deny":
            tx_line(guard.deny(_resolve(args.id), f"human:{args.approver}", args.note))
        elif args.cmd == "transactions":
            with get_guard().sessions() as db:
                rows = db.scalars(select(Transaction).order_by(Transaction.created_at.desc()).limit(args.limit)).all()
            console.print(tx_table(rows, f"Last {len(rows)} transactions"))
        elif args.cmd == "audit":
            with get_guard().sessions() as db:
                rows = db.scalars(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(args.limit)).all()
            console.print(audit_table(list(reversed(rows)), f"Last {len(rows)} audit entries"))
        elif args.cmd == "verify":
            with get_guard().sessions() as db:
                r = audit.verify(db)
            if r.ok:
                console.print(f"[green]OK[/]: {r.entries} entries, chain intact. Head hash {r.head_hash}")
                return 0
            console.print(f"[bold red]BROKEN at entry #{r.bad_seq}[/]: {r.problem}")
            return 1
        elif args.cmd == "wallet":
            s = guard.summary()
            cur = s["currency"]
            console.print(f"Wallet: {s['wallet']}   Day: {s['day']}")
            if s["balance_cents"] is not None:
                console.print(f"Balance: {fmt(s['balance_cents'], cur)}")
            console.print(f"Spent or held today: {fmt(s['used_today_cents'], cur)} of {fmt(s['daily_cap_cents'], cur)} "
                          f"(remaining {fmt(s['remaining_today_cents'], cur)}); "
                          f"pending confirmations: {s['pending_confirmations']}")
    except GuardError as exc:
        console.print(f"[red]{exc.code}: {exc.message}[/]")
        return 1
    return 0
