import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select

from app.config import get_settings
from app.guard import GuardError, Proposal, get_guard
from app.models import Transaction
from app.money import to_cents
from app.schemas import DecisionIn, ProposeIn, TransactionOut

router = APIRouter(prefix="/transactions", tags=["transactions"])


def require_approver(x_approver_token: str | None = Header(default=None)) -> None:
    """Human decisions over HTTP need APPROVER_TOKEN. Agents only ever get the propose endpoint."""
    expected = get_settings().approver_token
    if not expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "HTTP approval is disabled (APPROVER_TOKEN not set). Confirm with the CLI: "
                            "python -m cli confirm <id>")
    if not x_approver_token or not secrets.compare_digest(x_approver_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong X-Approver-Token.")


def _guard_call(fn, *args):
    try:
        return TransactionOut.of(fn(*args))
    except GuardError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def propose(body: ProposeIn):
    """Propose a payment. The response is the guard's decision:
    `executed` (auto-approved and paid), `pending_confirmation` (a human must confirm),
    `rejected` (hard no), or `failed` (approved but the wallet declined)."""
    p = Proposal(agent=body.agent, merchant=body.merchant, category=body.category, description=body.description,
                 amount_cents=to_cents(body.amount), currency=body.currency, idempotency_key=body.idempotency_key)
    return _guard_call(get_guard().propose, p)


@router.get("", response_model=list[TransactionOut])
def list_transactions(status_: str | None = Query(None, alias="status"), limit: int = Query(50, ge=1, le=500)):
    get_guard().summary()  # expires stale holds so statuses are current
    q = select(Transaction).order_by(Transaction.created_at.desc()).limit(limit)
    if status_:
        q = q.where(Transaction.status == status_)
    with get_guard().sessions() as db:
        return [TransactionOut.of(t) for t in db.scalars(q)]


@router.get("/{tx_id}", response_model=TransactionOut)
def get_transaction(tx_id: str):
    with get_guard().sessions() as db:
        tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(404, "Transaction not found")
    return TransactionOut.of(tx)


@router.post("/{tx_id}/confirm", response_model=TransactionOut, dependencies=[Depends(require_approver)])
def confirm(tx_id: str, body: DecisionIn):
    return _guard_call(get_guard().confirm, tx_id, f"human:{body.approver}")


@router.post("/{tx_id}/deny", response_model=TransactionOut, dependencies=[Depends(require_approver)])
def deny(tx_id: str, body: DecisionIn):
    return _guard_call(get_guard().deny, tx_id, f"human:{body.approver}", body.note)
