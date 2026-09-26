from fastapi import APIRouter

from app.config import get_settings
from app.guard import get_guard

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    s, g = get_settings(), get_guard()
    return {"status": "ok", "wallet": g.wallet.name, "policy": g.policy.fingerprint,
            "http_approval": bool(s.approver_token), "agent_llm": bool(s.groq_api_key)}
