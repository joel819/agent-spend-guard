"""agent-spend-guard CLI.

  python -m cli demo [--yes | --no] [--llm | --scripted] [--tamper]
  python -m cli propose --merchant M --amount 12.50 [--category C] [--description D]
  python -m cli pending
  python -m cli confirm <id> [--approver NAME]
  python -m cli deny <id> [--approver NAME] [--note TEXT]
  python -m cli transactions [--limit N]
  python -m cli audit [--limit N]
  python -m cli verify
  python -m cli wallet

Everything except `demo` works on the main database, the same one the API uses, so a human can
confirm from the terminal what an agent proposed over HTTP.
"""
import argparse
import sys

from cli import commands, demo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="show all three outcomes")
    g = d.add_mutually_exclusive_group()
    g.add_argument("--yes", action="store_const", const="yes", dest="confirm", help="auto-approve confirmations")
    g.add_argument("--no", action="store_const", const="no", dest="confirm", help="auto-deny confirmations")
    a = d.add_mutually_exclusive_group()
    a.add_argument("--llm", action="store_true", default=None, help="use the Groq agent (needs GROQ_API_KEY)")
    a.add_argument("--scripted", action="store_true", help="use the scripted agent")
    d.add_argument("--tamper", action="store_true", help="then tamper with the audit log and show detection")

    pr = sub.add_parser("propose", help="propose a payment as an agent")
    pr.add_argument("--merchant", required=True)
    pr.add_argument("--amount", required=True)
    pr.add_argument("--category", default="general")
    pr.add_argument("--description", default="manual proposal")
    pr.add_argument("--currency", default=None)
    pr.add_argument("--agent", default="cli-agent")

    sub.add_parser("pending", help="list payments waiting for confirmation")
    for name in ("confirm", "deny"):
        c = sub.add_parser(name, help=f"{name} a pending payment (you are the human)")
        c.add_argument("id", help="transaction id (or unique prefix)")
        c.add_argument("--approver", default="cli-operator")
        if name == "deny":
            c.add_argument("--note", default="")
    for name in ("transactions", "audit"):
        sub.add_parser(name).add_argument("--limit", type=int, default=25)
    sub.add_parser("verify", help="check the audit log's hash chain")
    sub.add_parser("wallet", help="balance and today's usage")

    args = p.parse_args(argv)
    if args.cmd == "demo":
        return demo.run(confirm_mode=args.confirm or "ask",
                        use_llm=False if args.scripted else args.llm, tamper=args.tamper)
    return commands.dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
