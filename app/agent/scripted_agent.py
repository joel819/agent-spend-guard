"""No-key fallback agent: a fixed shopping list chosen to hit all three outcomes under the
default policy (50.00 per transaction, 200.00 per day)."""
from app.agent.common import AfterFn, BeforeFn, ConfirmFn, Purchase, RunLog, submit
from app.guard import Guard

SHOPPING_LIST = [
    Purchase("Groq Cloud", "software", "API credits top-up", "20.00"),                  # auto-approve
    Purchase("Namecheap", "software", "Domain renewal: agent-demo.dev", "12.99"),      # auto-approve
    Purchase("PyCon Europe", "events", "Conference ticket (1 day)", "149.00"),        # needs confirmation
    Purchase("Lambda Cloud", "compute", "GPU hours for fine-tuning", "30.00"),        # daily cap: reject
]


def run(guard: Guard, confirm: ConfirmFn, items: list[Purchase] | None = None,
        before: BeforeFn | None = None, after: AfterFn | None = None) -> RunLog:
    log = RunLog()
    for item in items or SHOPPING_LIST:
        submit(guard, "scripted-agent", item, confirm, log, before, after)
    return log
