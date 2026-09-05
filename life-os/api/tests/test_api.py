"""API-level tests: auth, ownership isolation, and the credential vault."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models.connections import Connection
from app.models.user import User
from app.security import decrypt_secrets, encrypt_secrets

client = TestClient(app)


@pytest.fixture
def auth(db, user) -> dict[str, str]:
    from app.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_healthz_needs_no_auth():
    assert client.get("/healthz").json()["status"] == "ok"


def test_protected_routes_reject_anonymous():
    for path in ("/api/v1/dashboard", "/api/v1/accounts", "/api/v1/bills", "/api/v1/connections"):
        assert client.get(path).status_code == 401, path


def test_invalid_token_is_rejected():
    response = client.get("/api/v1/accounts", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_login_rejects_wrong_password(db, user):
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password-here"}
    )
    assert response.status_code == 401
    assert "Incorrect" in response.json()["detail"]


def test_login_and_me_round_trip(db, user):
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "test-password-123"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == user.email


def test_registration_closes_after_the_first_account(db, user):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "someone-else@example.com", "password": "another-long-password"},
    )
    assert response.status_code == 403
    assert "closed" in response.json()["detail"].lower()


def test_short_passwords_are_rejected(db):
    response = client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert response.status_code == 422


def test_account_crud_and_net_worth(db, user, auth):
    created = client.post(
        "/api/v1/accounts",
        json={"name": "Test Visa", "type": "credit", "current_balance": 1000, "credit_limit": 5000},
        headers=auth,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_liability"] is True
    assert body["signed_balance"] == -1000

    account_id = body["id"]
    patched = client.patch(
        f"/api/v1/accounts/{account_id}", json={"current_balance": 750}, headers=auth
    )
    assert patched.json()["signed_balance"] == -750

    assert client.get("/api/v1/finance/net-worth", headers=auth).json()["liabilities"] == 750
    assert client.delete(f"/api/v1/accounts/{account_id}", headers=auth).status_code == 204


def test_users_cannot_touch_each_others_accounts(db, user, auth):
    from app.security import create_access_token, hash_password

    created = client.post(
        "/api/v1/accounts", json={"name": "Private", "current_balance": 100}, headers=auth
    )
    account_id = created.json()["id"]

    intruder = User(
        email="intruder@example.com",
        hashed_password=hash_password("intruder-password"),
        display_name="Intruder",
    )
    db.add(intruder)
    db.commit()
    other = {"Authorization": f"Bearer {create_access_token(intruder.id)}"}

    assert client.get("/api/v1/accounts", headers=other).json() == []
    assert client.patch(f"/api/v1/accounts/{account_id}", json={"name": "x"}, headers=other).status_code == 404
    assert client.delete(f"/api/v1/accounts/{account_id}", headers=other).status_code == 404


def test_debt_details_rejected_on_asset_accounts(db, user, auth):
    account = client.post(
        "/api/v1/accounts", json={"name": "Savings", "type": "depository"}, headers=auth
    ).json()
    response = client.put(
        f"/api/v1/accounts/{account['id']}/debt", json={"apr": 5.0}, headers=auth
    )
    assert response.status_code == 400


def test_task_completion_stamps_a_timestamp(db, user, auth):
    task = client.post("/api/v1/tasks", json={"title": "Ship it", "priority": 1}, headers=auth).json()
    assert task["completed_at"] is None

    done = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"}, headers=auth).json()
    assert done["completed_at"] is not None

    reopened = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "todo"}, headers=auth).json()
    assert reopened["completed_at"] is None


def test_connector_catalogue_is_shaped_for_the_ui(db, user, auth):
    catalogue = client.get("/api/v1/connectors", headers=auth).json()
    plaid = next(c for c in catalogue if c["slug"] == "plaid")
    assert plaid["mode"] == "pull"
    assert any(field["secret"] for field in plaid["fields"])
    assert "accounts" in plaid["provides"]


def test_connection_secrets_are_encrypted_and_never_returned(db, user, auth):
    response = client.post(
        "/api/v1/connections",
        json={
            "connector_slug": "plaid",
            "display_name": "Chase via Plaid",
            "config": {"environment": "sandbox"},
            "secrets": {"client_id": "abc123", "secret": "shhh", "access_token": "access-sekrit"},
        },
        headers=auth,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["has_secrets"] is True

    serialized = str(body)
    for secret in ("abc123", "shhh", "access-sekrit"):
        assert secret not in serialized, "secrets must never round-trip to the client"

    stored = db.scalars(select(Connection).where(Connection.id == body["id"])).one()
    assert "access-sekrit" not in (stored.secrets_encrypted or "")
    assert decrypt_secrets(stored.secrets_encrypted)["access_token"] == "access-sekrit"


def test_partial_secret_update_preserves_the_others(db, user, auth):
    created = client.post(
        "/api/v1/connections",
        json={
            "connector_slug": "plaid",
            "config": {"environment": "sandbox"},
            "secrets": {"client_id": "id-1", "secret": "sec-1", "access_token": "tok-1"},
        },
        headers=auth,
    ).json()

    client.patch(
        f"/api/v1/connections/{created['id']}",
        json={"secrets": {"access_token": "tok-2"}},
        headers=auth,
    )
    db.expire_all()
    stored = db.scalars(select(Connection).where(Connection.id == created["id"])).one()
    secrets = decrypt_secrets(stored.secrets_encrypted)
    assert secrets == {"client_id": "id-1", "secret": "sec-1", "access_token": "tok-2"}


def test_incomplete_connection_is_flagged_needs_setup(db, user, auth):
    response = client.post(
        "/api/v1/connections",
        json={"connector_slug": "github_work", "config": {}, "secrets": {}},
        headers=auth,
    )
    body = response.json()
    assert body["status"] == "needs_setup"
    assert "required" in body["last_error"]


def test_unknown_connector_is_rejected(db, user, auth):
    response = client.post(
        "/api/v1/connections", json={"connector_slug": "not-real"}, headers=auth
    )
    assert response.status_code == 404


def test_sync_endpoint_refuses_push_only_connectors(db, user, auth):
    created = client.post(
        "/api/v1/connections",
        json={"connector_slug": "fidelity_csv", "config": {"institution": "Fidelity"}},
        headers=auth,
    ).json()
    response = client.post(f"/api/v1/connections/{created['id']}/sync", headers=auth)
    assert response.status_code == 400
    assert "pushed data" in response.json()["detail"]


def test_csv_upload_creates_accounts_and_logs_the_run(db, user, auth, fixture_text):
    created = client.post(
        "/api/v1/connections",
        json={"connector_slug": "fidelity_csv", "config": {"institution": "Fidelity"}},
        headers=auth,
    ).json()

    upload = client.post(
        f"/api/v1/connections/{created['id']}/ingest",
        files={"file": ("positions.csv", fixture_text("fidelity_positions.csv"), "text/csv")},
        headers=auth,
    )
    assert upload.status_code == 200
    run = upload.json()
    assert run["status"] == "success"
    assert run["created_count"] > 0

    accounts = client.get("/api/v1/accounts", headers=auth).json()
    assert any(a["institution"] == "Fidelity" for a in accounts)

    runs = client.get(f"/api/v1/connections/{created['id']}/runs", headers=auth).json()
    assert len(runs) == 1


def test_bad_upload_is_recorded_as_a_failed_run(db, user, auth):
    created = client.post(
        "/api/v1/connections", json={"connector_slug": "fidelity_csv"}, headers=auth
    ).json()
    upload = client.post(
        f"/api/v1/connections/{created['id']}/ingest",
        files={"file": ("junk.csv", "nothing,useful\n", "text/csv")},
        headers=auth,
    )
    assert upload.json()["status"] == "failed"
    assert "Unrecognised" in upload.json()["message"] or "No CSV" in upload.json()["message"]


def test_health_ingest_requires_the_token(db, user, auth):
    client.post("/api/v1/connections", json={"connector_slug": "apple_health"}, headers=auth)

    assert client.post("/api/v1/ingest/health", json={}).status_code == 401
    assert client.post(
        "/api/v1/ingest/health", json={}, headers={"X-Ingest-Token": "wrong"}
    ).status_code == 401


def test_health_ingest_accepts_a_device_payload(db, user, auth, fixture_text):
    created = client.post(
        "/api/v1/connections", json={"connector_slug": "apple_health"}, headers=auth
    ).json()

    response = client.post(
        f"/api/v1/ingest/health?connection_id={created['id']}",
        content=fixture_text("health_auto_export.json"),
        headers={"X-Ingest-Token": settings.ingest_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    summary = client.get("/api/v1/health/summary", headers=auth).json()
    assert "steps" in summary["available"]


def test_dashboard_returns_every_section(db, user, auth):
    body = client.get("/api/v1/dashboard?refresh=true", headers=auth).json()
    for section in ("finance", "investments", "debt", "bills", "tasks", "health", "insights", "system"):
        assert section in body, section


def test_vault_round_trip_and_tamper_resistance():
    blob = encrypt_secrets({"token": "value"})
    assert decrypt_secrets(blob) == {"token": "value"}
    # A corrupted blob returns empty rather than raising into a request handler.
    assert decrypt_secrets(blob[:-6] + "AAAAAA") == {}
    assert decrypt_secrets(None) == {}
