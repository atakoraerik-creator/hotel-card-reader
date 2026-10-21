from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from doorcard.web.app import create_app
from doorcard.web.config import WebSettings
from doorcard.web.models import Card, Guest, Room, User


def _csrf(client: TestClient, path: str = "/dashboard") -> str:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.text[:300])
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def _login(
    client: TestClient, email: str = "admin@horizon.test", password: str = "Admin!23456"
) -> None:
    token = _csrf(client, "/login")
    response = client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


@pytest.fixture
def client(tmp_path):
    settings = WebSettings(
        database_url=f"sqlite:///{(tmp_path / 'web-test.db').as_posix()}",
        secret_key="web-test-secret-key-with-enough-entropy",
        seed_demo=True,
        login_max_attempts=3,
    )
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client


def test_health_login_and_authentication_redirect(client: TestClient) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["hardware_write_enabled"] is False

    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert "Welcome back" in login_page.text
    assert "csrf_token" in login_page.text


def test_invalid_login_and_csrf_rejection(client: TestClient) -> None:
    token = _csrf(client, "/login")
    response = client.post(
        "/login",
        data={"csrf_token": token, "email": "admin@horizon.test", "password": "wrong-password"},
    )
    assert response.status_code == 200
    assert "incorrect" in response.text

    _login(client)
    response = client.post("/logout", data={"csrf_token": "not-a-token"})
    assert response.status_code == 400
    assert "Invalid or expired form token" in response.text


def test_login_throttle_after_repeated_failures(client: TestClient) -> None:
    token = _csrf(client, "/login")
    for _ in range(3):
        response = client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "admin@horizon.test",
                "password": "wrong-password",
            },
        )
        assert response.status_code == 200

    response = client.post(
        "/login",
        data={
            "csrf_token": token,
            "email": "admin@horizon.test",
            "password": "Admin!23456",
        },
    )
    assert response.status_code == 200
    assert "Too many attempts" in response.text


def test_admin_can_create_team_member(client: TestClient) -> None:
    _login(client)
    token = _csrf(client, "/users/new")
    response = client.post(
        "/users/new",
        data={
            "csrf_token": token,
            "full_name": "Night Auditor",
            "username": "night.auditor",
            "email": "night.auditor@horizon.test",
            "role": "receptionist",
            "active": "1",
            "password": "NightAudit!234",
            "password_confirm": "NightAudit!234",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.db.session() as db:
        member = db.scalar(select(User).where(User.username == "night.auditor"))
        assert member is not None
        assert member.role == "receptionist"
        assert member.active is True

    token = _csrf(client, "/users/new")
    response = client.post(
        "/users/new",
        data={
            "csrf_token": token,
            "full_name": "Duplicate",
            "username": "night.auditor",
            "email": "night.auditor@horizon.test",
            "role": "receptionist",
            "active": "1",
            "password": "NightAudit!234",
            "password_confirm": "NightAudit!234",
        },
    )
    assert response.status_code == 200
    assert "already in use" in response.text


def test_all_authenticated_pages_render(client: TestClient) -> None:
    _login(client)
    pages = [
        "/dashboard",
        "/rooms",
        "/rooms/new",
        "/guests",
        "/guests/new",
        "/cards",
        "/cards/issue",
        "/encoder",
        "/activity",
        "/users",
        "/users/new",
        "/settings",
    ]
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert "<html" in response.text


def test_room_create_update_and_duplicate(client: TestClient) -> None:
    _login(client)
    token = _csrf(client, "/rooms/new")
    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": token,
            "number": "209",
            "room_type": "Deluxe King",
            "floor": "2",
            "status": "available",
            "notes": "Quiet side",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.db.session() as db:
        room = db.scalar(select(Room).where(Room.number == "209"))
        assert room is not None
        room_id = room.id

    token = _csrf(client, f"/rooms/{room_id}/edit")
    response = client.post(
        f"/rooms/{room_id}/edit",
        data={
            "csrf_token": token,
            "number": "209",
            "room_type": "Executive Suite",
            "floor": "2",
            "status": "maintenance",
            "notes": "Deep clean",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    token = _csrf(client, "/rooms/new")
    response = client.post(
        "/rooms/new",
        data={
            "csrf_token": token,
            "number": "209",
            "room_type": "Deluxe King",
            "floor": "2",
            "status": "available",
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert "already exists" in response.text


def test_guest_checkin_card_issue_replace_cancel(client: TestClient) -> None:
    _login(client)
    with client.app.state.db.session() as db:
        room = db.scalar(select(Room).where(Room.number == "103"))
        assert room is not None
        room_id = room.id

    expiry = (date.today() + timedelta(days=2)).isoformat()
    token = _csrf(client, "/guests/new")
    response = client.post(
        "/guests/new",
        data={
            "csrf_token": token,
            "full_name": "Test Guest",
            "email": "test.guest@example.test",
            "phone": "+1 555 0199",
            "document_id": "T-991",
            "room_id": str(room_id),
            "check_in": date.today().isoformat(),
            "check_out": expiry,
            "status": "checked_in",
            "notes": "Late arrival",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.db.session() as db:
        guest = db.scalar(select(Guest).where(Guest.full_name == "Test Guest"))
        assert guest is not None
        guest_id = guest.id
        assert db.get(Room, room_id).status == "occupied"

    token = _csrf(client, "/cards/issue")
    response = client.post(
        "/cards/issue",
        data={
            "csrf_token": token,
            "guest_id": str(guest_id),
            "expires_at": expiry,
            "notes": "Web test card",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.db.session() as db:
        card = db.scalar(select(Card).where(Card.guest_id == guest_id))
        assert card is not None
        card_id = card.id
        card_number = card.card_number
        assert card.status == "active"

    detail = client.get(f"/cards/{card_id}")
    assert detail.status_code == 200
    assert card_number in detail.text

    token = _csrf(client, f"/cards/{card_id}")
    response = client.post(
        f"/cards/{card_id}/replace",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.db.session() as db:
        old_card = db.get(Card, card_id)
        assert old_card.status == "replaced"
        replacement = db.get(Card, old_card.replaced_by_card_id)
        assert replacement is not None
        assert replacement.status == "active"
        replacement_id = replacement.id

    token = _csrf(client, f"/cards/{replacement_id}")
    response = client.post(
        f"/cards/{replacement_id}/cancel",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client.app.state.db.session() as db:
        assert db.get(Card, replacement_id).status == "cancelled"


def test_receptionist_cannot_access_admin_pages(client: TestClient) -> None:
    _login(client, "reception@horizon.test", "Reception!23456")
    assert client.get("/dashboard").status_code == 200
    assert client.get("/rooms").status_code == 200
    assert client.get("/users").status_code == 403
    assert client.get("/settings").status_code == 403


def test_encoder_simulation_check_and_detect(client: TestClient) -> None:
    _login(client)
    page = client.get("/encoder")
    assert page.status_code == 200
    assert "Simulation mode" in page.text

    token = _csrf(client, "/encoder")
    response = client.post(
        "/encoder/check", data={"csrf_token": token}, follow_redirects=False
    )
    assert response.status_code == 303

    token = _csrf(client, "/encoder")
    response = client.post(
        "/encoder/detect",
        data={"csrf_token": token, "sample": "mifare_classic_1k"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    page = client.get("/encoder")
    assert page.status_code == 200
    assert "MIFARE Classic 1K" in page.text
    assert "Disabled" in page.text


def test_settings_update_and_logout(client: TestClient) -> None:
    _login(client)
    token = _csrf(client, "/settings")
    response = client.post(
        "/settings",
        data={
            "csrf_token": token,
            "hotel_name": "Harbor House",
            "hotel_address": "2 Marina Way",
            "hotel_phone": "+1 555 0100",
            "hotel_timezone": "UTC",
            "card_validity_days": "4",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    dashboard = client.get("/dashboard")
    assert "Harbor House" in dashboard.text

    token = _csrf(client, "/dashboard")
    response = client.post(
        "/logout", data={"csrf_token": token}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_seed_users_have_distinct_roles(client: TestClient) -> None:
    with client.app.state.db.session() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        reception = db.scalar(select(User).where(User.username == "reception"))
        assert admin is not None and admin.role == "administrator"
        assert reception is not None and reception.role == "receptionist"


def test_render_environment_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DOORCARD_WEB_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("DOORCARD_WEB_PORT", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "hotel-card-reader.onrender.com")
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("DOORCARD_WEB_SECRET", "render-test-secret-with-enough-length")

    settings = WebSettings.from_env()
    assert settings.allowed_hosts == ("hotel-card-reader.onrender.com",)
    assert settings.port == 10000


def test_unknown_page_renders_error_template(client: TestClient) -> None:
    _login(client)
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "Request could not be completed" in response.text
    assert "Page not found" in response.text or "Not Found" in response.text
