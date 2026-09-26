"""Load and validate spend_policy.toml. An invalid policy stops the app from starting:
running with a half-parsed spending policy is worse than not running."""
import hashlib
import tomllib
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import get_settings
from app.money import to_cents


class PolicyError(Exception):
    pass


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    per_transaction_cap_cents: int = Field(gt=0)
    daily_cap_cents: int = Field(gt=0)
    timezone: str
    confirmation_timeout_minutes: int = Field(ge=1, le=1440)
    blocked_categories: frozenset[str] = frozenset()
    always_confirm_categories: frozenset[str] = frozenset()
    fingerprint: str = ""

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {v!r}") from None
        return v

    @model_validator(mode="after")
    def _caps(self) -> "Policy":
        if self.per_transaction_cap_cents > self.daily_cap_cents:
            raise ValueError("per_transaction_cap is larger than daily_cap")
        if overlap := self.blocked_categories & self.always_confirm_categories:
            raise ValueError(f"categories both blocked and always_confirm: {sorted(overlap)}")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def parse_policy(text: str) -> Policy:
    try:
        raw = tomllib.loads(text)
        limits = raw["limits"]
        cats = raw.get("categories", {})
        policy = Policy(
            currency=limits["currency"],
            per_transaction_cap_cents=to_cents(limits["per_transaction_cap"]),
            daily_cap_cents=to_cents(limits["daily_cap"]),
            timezone=limits.get("timezone", "UTC"),
            confirmation_timeout_minutes=raw.get("confirmation", {}).get("timeout_minutes", 15),
            blocked_categories=frozenset(c.lower() for c in cats.get("blocked", [])),
            always_confirm_categories=frozenset(c.lower() for c in cats.get("always_confirm", [])),
        )
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"spend_policy.toml is not valid TOML: {exc}") from None
    except KeyError as exc:
        raise PolicyError(f"spend_policy.toml is missing {exc}") from None
    except (ValidationError, ValueError) as exc:
        raise PolicyError(f"spend_policy.toml is invalid: {exc}") from None
    fp = hashlib.sha256(policy.model_dump_json(exclude={"fingerprint"}).encode()).hexdigest()[:16]
    return policy.model_copy(update={"fingerprint": fp})


def load_policy(path: Path) -> Policy:
    try:
        return parse_policy(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PolicyError(f"policy file not found: {path}") from None


@lru_cache
def get_policy() -> Policy:
    return load_policy(get_settings().policy_file)
