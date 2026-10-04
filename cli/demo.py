"""The CLI demo: an agent works through a shopping list and the guard produces all three outcomes.

Runs against a fresh demo database each time (data/demo.db), so the result is the same every run
no matter what was spent today in the main database.
"""
import sys

from rich.panel import Panel
from rich.prompt import Confirm
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app import audit
from app.agent import groq_agent, scripted_agent
from app.config import get_settings
from app.db import init_db, make_engine
from app.guard import build_guard
from app.models import AuditEntry, Transaction
from app.money import fmt
from app.policy.loader import get_policy
from app.wallet.mock_wallet import MockWallet
from cli.render import audit_table, console, label, tx_line, tx_table


def _confirm_fn(mode: str):
    def ask(tx: Transaction) -> bool:
        console.print(f"  {label(tx.status)}  {tx.merchant}: {tx.description}, [bold]{fmt(tx.amount_cents, tx.currency)}[/]")
        console.print(f"  [dim]{tx.reason}[/]")
        if mode in ("yes", "no"):
            answer = mode == "yes"
            console.print(f"  [yellow]Human confirmation:[/] {'approve' if answer else 'deny'} (--{mode})")
            return answer
        if not sys.stdin.isatty():
            console.print("  [yellow]Human confirmation:[/] approve (no terminal attached; use --no to deny)")
            return True
        return Confirm.ask("  [yellow]Human, approve this payment?[/]", default=False)
    return ask


def run(confirm_mode: str = "ask", use_llm: bool | None = None, tamper: bool = False) -> int:
    s = get_settings()
    db_path = s.data_dir / "demo.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    policy = get_policy()
    wallet = None if s.stripe_secret_key else MockWallet(sessions)
    guard = build_guard(sessions=sessions, policy=policy, wallet=wallet)

    cur = policy.currency
    console.print(Panel.fit(
        f"per-transaction cap [bold]{fmt(policy.per_transaction_cap_cents, cur)}[/]   "
        f"daily cap [bold]{fmt(policy.daily_cap_cents, cur)}[/]   wallet [bold]{guard.wallet.name}[/]\n"
        f"[green]under the per-transaction cap[/] -> auto-approve   "
        f"[yellow]over it[/] -> human confirms   [red]past the daily cap[/] -> hard reject",
        title="agent-spend-guard demo", subtitle=f"policy {policy.fingerprint}"))

    confirm = _confirm_fn(confirm_mode)
    before, after = _hooks()
    use_llm = bool(s.groq_api_key) if use_llm is None else use_llm
    summary = None
    if use_llm:
        console.print(f"\n[bold]Agent:[/] Groq LLM ({s.groq_model}) with a propose_payment tool\n")
        try:
            log, summary = groq_agent.run(guard, confirm, s, before=before, after=after)
        except groq_agent.AgentError as exc:
            console.print(f"[red]LLM agent failed ({exc}); switching to the scripted agent.[/]\n")
            use_llm = False
    if not use_llm:
        console.print("\n[bold]Agent:[/] scripted shopping list (no GROQ_API_KEY)\n")
        log = scripted_agent.run(guard, confirm, before=before, after=after)

    st = guard.summary()
    console.print(f"\nSpent or held today: [bold]{fmt(st['used_today_cents'], cur)}[/] of "
                  f"{fmt(st['daily_cap_cents'], cur)}   remaining: {fmt(st['remaining_today_cents'], cur)}"
                  + (f"   wallet balance: {fmt(st['balance_cents'], cur)}" if st["balance_cents"] is not None else ""))
    if summary:
        console.print(Panel(summary, title="Agent's summary", title_align="left"))

    with sessions() as db:
        console.print()
        console.print(tx_table(db.scalars(select(Transaction).order_by(Transaction.created_at)).all(), "Transactions"))
        console.print(audit_table(db.scalars(select(AuditEntry).order_by(AuditEntry.seq)).all(), "Audit log"))
        _print_verify(audit.verify(db))

    if tamper:
        with engine.begin() as conn:
            seq = conn.execute(text("SELECT min(seq) FROM audit_log WHERE event = 'proposed' "
                                    "AND data LIKE '%149.00%'")).scalar()
            if seq is None:  # LLM agent may have used other amounts: tamper with the first proposal
                seq = conn.execute(text("SELECT min(seq) FROM audit_log WHERE event = 'proposed'")).scalar()
            console.print(f"\n[bold]Tamper test:[/] rewriting the amount in audit entry #{seq} directly in "
                          "SQLite, as someone covering their tracks would...")
            conn.execute(text("UPDATE audit_log SET data = replace(data, '.00 EUR', '.01 EUR') WHERE seq = :s"),
                         {"s": seq})
        with sessions() as db:
            _print_verify(audit.verify(db))

    counts = {"approve": 0, "confirm": 0, "reject": 0}
    for _, tx in log.steps:
        counts[tx.decision] += 1
    console.print(f"\nOutcomes: [green]{counts['approve']} auto-approved[/], "
                  f"[yellow]{counts['confirm']} needed a human[/], [red]{counts['reject']} hard-rejected[/]"
                  f"   [dim](demo database: {db_path})[/]")
    return 0


def _hooks():
    """Print each proposal and its final outcome as the agent works."""
    step = {"n": 0}

    def before(agent: str, item) -> None:
        step["n"] += 1
        console.print(f"[bold]{step['n']}.[/] {agent} proposes {item.merchant}, {item.amount} {item.currency}")

    def after(tx: Transaction) -> None:
        tx_line(tx)
        console.print()

    return before, after


def _print_verify(r) -> None:
    if r.ok:
        console.print(f"[green]Audit chain verified:[/] {r.entries} entries intact. Head hash {r.head_hash[:16]}…")
    else:
        console.print(f"[bold red]Audit chain BROKEN at entry #{r.bad_seq}:[/] {r.problem}")
