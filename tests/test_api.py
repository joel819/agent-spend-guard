import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from main import app

BODY = {"agent": "api-agent", "merchant": "Acme", "category": "software", "description": "credits",
        "currency": "EUR"}


@pytest.fixture
def client(guard):
    with TestClient(app) as c:
        yield c


def post(client, amount, **extra):
    return client.post("/transactions", json={**BODY, "amount": amount, **extra})


def test_three_outcomes_over_http(client):
    assert post(client, "20.00").json()["status"] == "executed"
    pending = post(client, "149.00").json()
    assert pending["status"] == "pending_confirmation" and pending["expires_at"]
    rejected = post(client, "40.00").json()
    assert rejected["status"] == "rejected" and rejected["rule"] == "daily_cap"


def test_http_confirm_disabled_without_approver_token(client):
    tx = post(client, "149.00").json()
    r = client.post(f"/transactions/{tx['id']}/confirm", json={"approver": "me"})
    assert r.status_code == 403 and "python -m cli confirm" in r.json()["detail"]


def test_http_confirm_with_approver_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "approver_token", "s3cret")
    tx = post(client, "149.00").json()
    assert client.post(f"/transactions/{tx['id']}/confirm", json={"approver": "me"},
                       headers={"X-Approver-Token": "wrong"}).status_code == 401
    ok = client.post(f"/transactions/{tx['id']}/confirm", json={"approver": "alice"},
                     headers={"X-Approver-Token": "s3cret"}).json()
    assert ok["status"] == "executed" and ok["decided_by"] == "human:alice"
    again = client.post(f"/transactions/{tx['id']}/deny", json={"approver": "alice"},
                        headers={"X-Approver-Token": "s3cret"})
    assert again.status_code == 409


@pytest.mark.parametrize("amount", ["0", "-5.00", "1.234", "abc"])
def test_invalid_amounts(client, amount):
    assert post(client, amount).status_code == 422


def test_idempotency_over_http(client):
    a = post(client, "10.00", idempotency_key="abc").json()
    b = post(client, "10.00", idempotency_key="abc").json()
    assert a["id"] == b["id"]
    assert post(client, "11.00", idempotency_key="abc").status_code == 409


def test_wallet_policy_audit_endpoints(client):
    post(client, "20.00")
    w = client.get("/wallet").json()
    assert w["spent_or_held_today"] == "20.00" and w["remaining_today"] == "180.00" and w["balance"] == "980.00"
    assert client.get("/policy").json()["per_transaction_cap"] == "50.00"
    events = [e["event"] for e in client.get("/audit").json()]
    assert events[:3] == ["executed", "auto_approved", "proposed"]
    assert client.get("/audit/verify").json()["ok"] is True
    assert client.get("/transactions", params={"status": "executed"}).json()[0]["amount"] == "20.00"
