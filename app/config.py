"""Environment settings. The spending rules themselves live in spend_policy.toml."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "agent-spend-guard"
    policy_file: Path = ROOT / "spend_policy.toml"
    data_dir: Path = Path("./data")
    database_url: str = ""  # defaults to sqlite in data_dir
    seed_on_startup: bool = True
    opening_balance: str = "5000.00"  # mock wallet balance when first created

    # Human approval over HTTP. Empty = confirm/deny only via the CLI (local operator).
    # Agents must never be given this token.
    approver_token: str = ""

    # Payments: Stripe TEST mode only (sk_test_...). Empty = mock wallet.
    stripe_secret_key: str = ""

    # Demo agent (LLM)
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"
    agent_max_steps: int = 8

    @property
    def sqlite_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'spend_guard.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
