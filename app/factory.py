import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db import init_db
from app.guard import get_guard
from app.routers import audit, health, transactions, wallet

log = logging.getLogger("uvicorn.error")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_db()
    guard = get_guard()  # loads + validates the policy: a bad spend_policy.toml stops startup here
    if s.seed_on_startup:
        from scripts.seed import seed

        seed(verbose=False)
    p = guard.policy
    log.info("Spend policy %s: %s per transaction, %s per day (%s). Wallet: %s", p.fingerprint,
             p.per_transaction_cap_cents / 100, p.daily_cap_cents / 100, p.currency, guard.wallet.name)
    if not s.approver_token:
        log.warning("APPROVER_TOKEN not set: confirmations only via the CLI (python -m cli confirm <id>).")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan,
                  description="Spending guard for AI agents: auto-approve under the per-transaction cap, "
                              "human confirmation over it, hard reject at the daily cap. Full audit log.")
    for r in (health.router, transactions.router, wallet.router, audit.router):
        app.include_router(r)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app
