from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import WebSettings
from .constants import (
    CARD_STATUS_LABELS,
    CARD_STATUSES,
    GUEST_STATUS_LABELS,
    GUEST_STATUSES,
    ROOM_STATUS_LABELS,
    ROOM_STATUSES,
    ROOM_TYPES,
    USER_ROLE_LABELS,
    USER_ROLES,
    label_for,
)
from .db import Database
from .deps import LoginRequired, current_user, get_db, require_admin, require_user
from .encoder import EncoderBridge
from .models import ActivityLog, Card, Guest, Room, User
from .security import (
    LoginThrottle,
    check_csrf,
    client_ip,
    ensure_csrf,
    hash_password,
    password_errors,
    safe_next,
    verify_password,
)
from .seed import seed_demo
from .services import (
    cancel_card,
    card_expiry_from_date,
    card_history,
    dashboard_stats,
    expiring_cards,
    issue_card,
    load_hotel,
    log_activity,
    recalculate_room_status,
    recent_activity,
    refresh_expired_cards,
    replace_card,
    save_hotel,
    status_label,
)

LOGGER = logging.getLogger("doorcard.web")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PAGE_SIZE = 200


def _flash(request: Request, message: str, category: str = "success") -> None:
    items = list(request.session.get("_flashes", []))
    items.append({"message": message, "category": category})
    request.session["_flashes"] = items[-5:]


def _pop_flashes(request: Request) -> list[dict]:
    return list(request.session.pop("_flashes", []))


def _safe_int(value: object, default: int | None = None) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _form_text(form, key: str) -> str:
    return str(form.get(key, "") or "").strip()


def _form_bool(form, key: str) -> bool:
    return str(form.get(key, "")).lower() in {"1", "true", "on", "yes"}


def _room_values(room: Room | None = None) -> dict:
    if room is None:
        return {
            "number": "",
            "room_type": ROOM_TYPES[0],
            "floor": "1",
            "status": "available",
            "notes": "",
        }
    return {
        "number": room.number,
        "room_type": room.room_type,
        "floor": str(room.floor),
        "status": room.status,
        "notes": room.notes or "",
    }


def _guest_values(guest: Guest | None = None) -> dict:
    if guest is None:
        return {
            "full_name": "",
            "email": "",
            "phone": "",
            "document_id": "",
            "room_id": "",
            "check_in": "",
            "check_out": "",
            "status": "reserved",
            "notes": "",
        }
    return {
        "full_name": guest.full_name,
        "email": guest.email or "",
        "phone": guest.phone or "",
        "document_id": guest.document_id or "",
        "room_id": str(guest.room_id or ""),
        "check_in": guest.check_in.isoformat() if guest.check_in else "",
        "check_out": guest.check_out.isoformat() if guest.check_out else "",
        "status": guest.status,
        "notes": guest.notes or "",
    }


def _user_values(user: User | None = None) -> dict:
    if user is None:
        return {
            "username": "",
            "email": "",
            "full_name": "",
            "role": "receptionist",
            "active": True,
        }
    return {
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "active": user.active,
    }


def create_app(settings: WebSettings | None = None) -> FastAPI:
    settings = settings or WebSettings.from_env()
    app = FastAPI(
        title="Horizon Hotel Card Manager",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.db = Database(settings.database_url, settings.database_engine_options)
    app.state.db.create_all()
    if settings.seed_demo:
        with app.state.db.session() as db:
            seed_demo(db, hotel_name=settings.hotel_name)
    app.state.encoder = EncoderBridge(settings.encoder_mode)
    app.state.throttle = LoginThrottle(
        settings.login_max_attempts, settings.login_window_seconds
    )
    app.state.dummy_hash = hash_password("not-a-real-password-42")
    app.state.templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates = app.state.templates

    templates.env.filters["dt"] = lambda value: (
        value.strftime("%b %d, %Y %H:%M") if isinstance(value, datetime) else "—"
    )
    templates.env.filters["short_date"] = lambda value: (
        value.strftime("%b %d, %Y") if isinstance(value, (date, datetime)) else "—"
    )
    templates.env.filters["iso_date"] = lambda value: (
        value.isoformat() if isinstance(value, (date, datetime)) else ""
    )
    templates.env.filters["status_tone"] = lambda value: {
        "available": "success",
        "active": "success",
        "checked_in": "success",
        "occupied": "warning",
        "reserved": "info",
        "maintenance": "warning",
        "out_of_service": "danger",
        "checked_out": "neutral",
        "cancelled": "danger",
        "expired": "danger",
        "replaced": "neutral",
        "administrator": "gold",
        "receptionist": "info",
    }.get(str(value), "neutral")
    templates.env.filters["status_label"] = status_label
    templates.env.filters["initials"] = lambda value: "".join(
        part[0].upper() for part in str(value or "").split()[:2]
    ) or "?"
    templates.env.globals["label_for"] = label_for

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="doorcard_web_session",
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.secure_cookies,
    )
    if settings.allowed_hosts != ("*",):
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts)
        )

    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        return response

    def render(
        request: Request,
        template: str,
        *,
        user: User | None,
        active: str,
        db: Session,
        **context,
    ) -> HTMLResponse:
        payload = {
            "request": request,
            "user": user,
            "active": active,
            "hotel": load_hotel(db),
            "csrf_token": ensure_csrf(request),
            "flashes": _pop_flashes(request),
            "demo_enabled": settings.seed_demo,
            "app_settings": settings,
            "current_year": date.today().year,
            "today": date.today(),
            **context,
        }
        return templates.TemplateResponse(request, template, payload)

    def render_error(
        request: Request, status_code: int, title: str, message: str
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "status_code": status_code,
                "title": title,
                "message": message,
                "hotel_name": settings.hotel_name,
                "current_year": date.today().year,
            },
            status_code=status_code,
        )

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired) -> Response:
        target = request.url.path
        if request.url.query:
            target += f"?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        accept = request.headers.get("accept", "")
        if exc.status_code >= 400 and ("text/html" in accept or accept == "*/*"):
            return render_error(
                request,
                exc.status_code,
                "Request could not be completed",
                str(exc.detail),
            )
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.get("/healthz")
    def healthz(request: Request) -> dict:
        with request.app.state.db.session() as db:
            db.execute(select(1))
        return {"status": "ok", "service": "doorcard-web", "hardware_write_enabled": False}

    @app.get("/api/health")
    def api_health(request: Request) -> dict:
        return healthz(request)

    @app.get("/")
    def index(user: User | None = Depends(current_user)) -> RedirectResponse:
        return RedirectResponse("/dashboard" if user else "/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(
        request: Request,
        next: str = "",
        user: User | None = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> Response:
        if user is not None:
            return RedirectResponse("/dashboard", status_code=303)
        return render(
            request,
            "login.html",
            user=None,
            active="login",
            db=db,
            next_url=safe_next(next),
            errors={},
            email="",
        )

    @app.post("/login")
    async def login_submit(
        request: Request,
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        email = _form_text(form, "email").lower()
        password = str(form.get("password", ""))
        next_url = safe_next(_form_text(form, "next"))
        errors: dict[str, str] = {}
        if not email:
            errors["email"] = "Enter your email or username."
        if not password:
            errors["password"] = "Enter your password."
        if errors:
            return render(
                request,
                "login.html",
                user=None,
                active="login",
                db=db,
                next_url=next_url,
                errors=errors,
                email=email,
            )

        throttle_key = f"{client_ip(request)}:{email}"
        retry = app.state.throttle.retry_after(throttle_key)
        if retry:
            errors["form"] = f"Too many attempts. Try again in {retry} seconds."
            return render(
                request,
                "login.html",
                user=None,
                active="login",
                db=db,
                next_url=next_url,
                errors=errors,
                email=email,
            )

        user = db.scalar(
            select(User).where(
                or_(func.lower(User.email) == email, func.lower(User.username) == email)
            )
        )
        valid = verify_password(
            password, user.password_hash if user is not None else app.state.dummy_hash
        )
        if user is None or not user.active or not valid:
            app.state.throttle.fail(throttle_key)
            log_activity(
                db,
                user=None,
                action="auth.login.failed",
                description=f"Failed sign-in for {email}.",
                ip_address=client_ip(request),
            )
            db.commit()
            errors["form"] = "The email/username or password is incorrect."
            return render(
                request,
                "login.html",
                user=None,
                active="login",
                db=db,
                next_url=next_url,
                errors=errors,
                email=email,
            )

        app.state.throttle.reset(throttle_key)
        request.session.clear()
        request.session["user_id"] = user.id
        ensure_csrf(request)
        log_activity(
            db,
            user=user,
            action="auth.login",
            description=f"{user.full_name} signed in as {USER_ROLE_LABELS.get(user.role, user.role)}.",
            ip_address=client_ip(request),
        )
        db.commit()
        return RedirectResponse(next_url, status_code=303)

    @app.post("/logout")
    async def logout_confirm(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        log_activity(
            db,
            user=user,
            action="auth.logout",
            description=f"{user.full_name} signed out.",
            ip_address=client_ip(request),
        )
        db.commit()
        request.session.clear()
        request.session["csrf_token"] = ensure_csrf(request)
        _flash(request, "You have been signed out.", "info")
        return RedirectResponse("/login", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        stats = dashboard_stats(db)
        return render(
            request,
            "dashboard.html",
            user=user,
            active="dashboard",
            db=db,
            stats=stats,
            recent=recent_activity(db, 8),
            expiring=expiring_cards(db),
        )

    @app.get("/rooms", response_class=HTMLResponse)
    def rooms(
        request: Request,
        q: str = "",
        status: str = "",
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        query = select(Room)
        if q.strip():
            needle = f"%{q.strip()}%"
            query = query.where(or_(Room.number.ilike(needle), Room.room_type.ilike(needle)))
        if status in ROOM_STATUSES:
            query = query.where(Room.status == status)
        rooms_list = list(db.scalars(query.order_by(Room.number.asc())).all())
        return render(
            request,
            "rooms.html",
            user=user,
            active="rooms",
            db=db,
            rooms=rooms_list,
            q=q,
            selected_status=status,
            statuses=ROOM_STATUSES,
            status_labels=ROOM_STATUS_LABELS,
        )

    def room_form_response(
        request: Request,
        user: User,
        db: Session,
        *,
        form: dict,
        errors: dict[str, str],
        mode: str,
        room_id: int | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "room_form.html",
            user=user,
            active="rooms",
            db=db,
            form=form,
            errors=errors,
            mode=mode,
            room_id=room_id,
            room_types=ROOM_TYPES,
            statuses=ROOM_STATUSES,
            status_labels=ROOM_STATUS_LABELS,
        )

    @app.get("/rooms/new", response_class=HTMLResponse)
    def room_new(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        return room_form_response(
            request, user, db, form=_room_values(), errors={}, mode="new"
        )

    @app.post("/rooms/new")
    async def room_create(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values = _room_values()
        values.update(
            {
                "number": _form_text(form, "number"),
                "room_type": _form_text(form, "room_type"),
                "floor": _form_text(form, "floor"),
                "status": _form_text(form, "status"),
                "notes": _form_text(form, "notes"),
            }
        )
        errors: dict[str, str] = {}
        floor = _safe_int(values["floor"])
        if not values["number"]:
            errors["number"] = "Room number is required."
        elif db.scalar(select(func.count(Room.id)).where(Room.number == values["number"])):
            errors["number"] = "That room number already exists."
        if values["room_type"] not in ROOM_TYPES:
            errors["room_type"] = "Choose a valid room type."
        if floor is None or floor < 0 or floor > 200:
            errors["floor"] = "Floor must be a number between 0 and 200."
        if values["status"] not in ROOM_STATUSES:
            errors["status"] = "Choose a valid room status."
        if len(values["notes"]) > 2000:
            errors["notes"] = "Notes must be 2,000 characters or fewer."
        if errors:
            return room_form_response(
                request, user, db, form=values, errors=errors, mode="new"
            )
        room = Room(
            number=values["number"],
            room_type=values["room_type"],
            floor=floor,
            status=values["status"],
            notes=values["notes"] or None,
        )
        db.add(room)
        db.flush()
        log_activity(
            db,
            user=user,
            action="room.create",
            description=f"Created room {room.number} ({room.room_type}).",
            entity_type="room",
            entity_id=room.id,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, f"Room {room.number} was added.")
        return RedirectResponse("/rooms", status_code=303)

    @app.get("/rooms/{room_id}/edit", response_class=HTMLResponse)
    def room_edit(
        request: Request,
        room_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found.")
        return room_form_response(
            request, user, db, form=_room_values(room), errors={}, mode="edit", room_id=room.id
        )

    @app.post("/rooms/{room_id}/edit")
    async def room_update(
        request: Request,
        room_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found.")
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values = _room_values(room)
        values.update(
            {
                "number": _form_text(form, "number"),
                "room_type": _form_text(form, "room_type"),
                "floor": _form_text(form, "floor"),
                "status": _form_text(form, "status"),
                "notes": _form_text(form, "notes"),
            }
        )
        errors: dict[str, str] = {}
        floor = _safe_int(values["floor"])
        duplicate = db.scalar(
            select(func.count(Room.id)).where(
                Room.number == values["number"], Room.id != room.id
            )
        )
        if not values["number"]:
            errors["number"] = "Room number is required."
        elif duplicate:
            errors["number"] = "That room number already exists."
        if values["room_type"] not in ROOM_TYPES:
            errors["room_type"] = "Choose a valid room type."
        if floor is None or floor < 0 or floor > 200:
            errors["floor"] = "Floor must be a number between 0 and 200."
        if values["status"] not in ROOM_STATUSES:
            errors["status"] = "Choose a valid room status."
        if values["status"] != room.status:
            checked_in = db.scalar(
                select(func.count(Guest.id)).where(
                    Guest.room_id == room.id, Guest.status == "checked_in"
                )
            )
            if checked_in and values["status"] != "occupied":
                errors["status"] = (
                    "This room has a checked-in guest. Check the guest out before changing status."
                )
            elif not checked_in and values["status"] == "occupied":
                errors["status"] = "Mark a guest as checked in to occupy this room."
        if len(values["notes"]) > 2000:
            errors["notes"] = "Notes must be 2,000 characters or fewer."
        if errors:
            return room_form_response(
                request, user, db, form=values, errors=errors, mode="edit", room_id=room.id
            )
        room.number = values["number"]
        room.room_type = values["room_type"]
        room.floor = floor
        room.status = values["status"]
        room.notes = values["notes"] or None
        log_activity(
            db,
            user=user,
            action="room.update",
            description=f"Updated room {room.number}. Status: {status_label(room.status)}.",
            entity_type="room",
            entity_id=room.id,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, f"Room {room.number} was updated.")
        return RedirectResponse("/rooms", status_code=303)

    @app.get("/guests", response_class=HTMLResponse)
    def guests(
        request: Request,
        q: str = "",
        status: str = "",
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        query = select(Guest)
        if q.strip():
            needle = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Guest.full_name.ilike(needle),
                    Guest.email.ilike(needle),
                    Guest.document_id.ilike(needle),
                )
            )
        if status in GUEST_STATUSES:
            query = query.where(Guest.status == status)
        guests_list = list(db.scalars(query.order_by(Guest.created_at.desc())).all())
        return render(
            request,
            "guests.html",
            user=user,
            active="guests",
            db=db,
            guests=guests_list,
            q=q,
            selected_status=status,
            statuses=GUEST_STATUSES,
            status_labels=GUEST_STATUS_LABELS,
        )

    def guest_form_response(
        request: Request,
        user: User,
        db: Session,
        *,
        form: dict,
        errors: dict[str, str],
        mode: str,
        guest_id: int | None = None,
    ) -> HTMLResponse:
        rooms_list = list(db.scalars(select(Room).order_by(Room.number.asc())).all())
        return render(
            request,
            "guest_form.html",
            user=user,
            active="guests",
            db=db,
            form=form,
            errors=errors,
            mode=mode,
            guest_id=guest_id,
            rooms=rooms_list,
            statuses=GUEST_STATUSES,
            status_labels=GUEST_STATUS_LABELS,
        )

    @app.get("/guests/new", response_class=HTMLResponse)
    def guest_new(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        return guest_form_response(
            request, user, db, form=_guest_values(), errors={}, mode="new"
        )

    def _guest_form_values(form) -> tuple[dict, dict[str, str], int | None, date | None, date | None]:
        values = _guest_values()
        values.update(
            {
                "full_name": _form_text(form, "full_name"),
                "email": _form_text(form, "email"),
                "phone": _form_text(form, "phone"),
                "document_id": _form_text(form, "document_id"),
                "room_id": _form_text(form, "room_id"),
                "check_in": _form_text(form, "check_in"),
                "check_out": _form_text(form, "check_out"),
                "status": _form_text(form, "status"),
                "notes": _form_text(form, "notes"),
            }
        )
        errors: dict[str, str] = {}
        room_id = _safe_int(values["room_id"])
        check_in = _parse_date(values["check_in"])
        check_out = _parse_date(values["check_out"])
        if not values["full_name"]:
            errors["full_name"] = "Guest name is required."
        elif len(values["full_name"]) > 160:
            errors["full_name"] = "Guest name must be 160 characters or fewer."
        if values["email"] and not EMAIL_RE.match(values["email"]):
            errors["email"] = "Enter a valid email address."
        if values["room_id"] and room_id is None:
            errors["room_id"] = "Choose a valid room."
        if values["check_in"] and check_in is None:
            errors["check_in"] = "Use a valid check-in date."
        if values["check_out"] and check_out is None:
            errors["check_out"] = "Use a valid check-out date."
        if check_in and check_out and check_out <= check_in:
            errors["check_out"] = "Check-out must be after check-in."
        if values["status"] not in GUEST_STATUSES:
            errors["status"] = "Choose a valid guest status."
        if values["status"] == "checked_in" and room_id is None:
            errors["room_id"] = "A checked-in guest must have a room."
        if len(values["notes"]) > 2000:
            errors["notes"] = "Notes must be 2,000 characters or fewer."
        return values, errors, room_id, check_in, check_out

    @app.post("/guests/new")
    async def guest_create(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values, errors, room_id, check_in, check_out = _guest_form_values(form)
        room = db.get(Room, room_id) if room_id else None
        if values["room_id"] and room is None:
            errors["room_id"] = "That room does not exist."
        if room and values["status"] == "checked_in":
            if room.status in {"maintenance", "out_of_service"}:
                errors["room_id"] = "That room is not available for check-in."
            occupied = db.scalar(
                select(func.count(Guest.id)).where(
                    Guest.room_id == room.id, Guest.status == "checked_in"
                )
            )
            if occupied:
                errors["room_id"] = "That room already has a checked-in guest."
        if errors:
            return guest_form_response(
                request, user, db, form=values, errors=errors, mode="new"
            )
        guest = Guest(
            full_name=values["full_name"],
            email=values["email"] or None,
            phone=values["phone"] or None,
            document_id=values["document_id"] or None,
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            status=values["status"],
            notes=values["notes"] or None,
        )
        db.add(guest)
        db.flush()
        recalculate_room_status(db, room_id)
        log_activity(
            db,
            user=user,
            action="guest.create",
            description=f"Registered guest {guest.full_name}.",
            entity_type="guest",
            entity_id=guest.id,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, f"Guest {guest.full_name} was registered.")
        return RedirectResponse("/guests", status_code=303)

    @app.get("/guests/{guest_id}/edit", response_class=HTMLResponse)
    def guest_edit(
        request: Request,
        guest_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        guest = db.get(Guest, guest_id)
        if guest is None:
            raise HTTPException(status_code=404, detail="Guest not found.")
        return guest_form_response(
            request,
            user,
            db,
            form=_guest_values(guest),
            errors={},
            mode="edit",
            guest_id=guest.id,
        )

    @app.post("/guests/{guest_id}/edit")
    async def guest_update(
        request: Request,
        guest_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        guest = db.get(Guest, guest_id)
        if guest is None:
            raise HTTPException(status_code=404, detail="Guest not found.")
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values, errors, room_id, check_in, check_out = _guest_form_values(form)
        room = db.get(Room, room_id) if room_id else None
        old_room_id = guest.room_id
        if values["room_id"] and room is None:
            errors["room_id"] = "That room does not exist."
        if room and values["status"] == "checked_in":
            if room.status in {"maintenance", "out_of_service"}:
                errors["room_id"] = "That room is not available for check-in."
            occupied = db.scalar(
                select(func.count(Guest.id)).where(
                    Guest.room_id == room.id,
                    Guest.status == "checked_in",
                    Guest.id != guest.id,
                )
            )
            if occupied:
                errors["room_id"] = "That room already has a checked-in guest."
        if errors:
            return guest_form_response(
                request,
                user,
                db,
                form=values,
                errors=errors,
                mode="edit",
                guest_id=guest.id,
            )
        guest.full_name = values["full_name"]
        guest.email = values["email"] or None
        guest.phone = values["phone"] or None
        guest.document_id = values["document_id"] or None
        guest.room_id = room_id
        guest.check_in = check_in
        guest.check_out = check_out
        guest.status = values["status"]
        guest.notes = values["notes"] or None
        db.flush()
        recalculate_room_status(db, old_room_id)
        if room_id != old_room_id:
            recalculate_room_status(db, room_id)
        log_activity(
            db,
            user=user,
            action="guest.update",
            description=f"Updated guest {guest.full_name}.",
            entity_type="guest",
            entity_id=guest.id,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, f"Guest {guest.full_name} was updated.")
        return RedirectResponse("/guests", status_code=303)

    @app.get("/cards", response_class=HTMLResponse)
    def cards(
        request: Request,
        q: str = "",
        status: str = "",
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        refresh_expired_cards(db)
        query = select(Card).join(Card.room).join(Card.guest)
        if q.strip():
            needle = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Card.card_number.ilike(needle),
                    Room.number.ilike(needle),
                    Guest.full_name.ilike(needle),
                )
            )
        if status in CARD_STATUSES:
            query = query.where(Card.status == status)
        cards_list = list(
            db.scalars(query.order_by(Card.issued_at.desc(), Card.id.desc())).all()
        )
        return render(
            request,
            "cards.html",
            user=user,
            active="cards",
            db=db,
            cards=cards_list,
            q=q,
            selected_status=status,
            statuses=CARD_STATUSES,
            status_labels=CARD_STATUS_LABELS,
        )

    @app.get("/cards/issue", response_class=HTMLResponse)
    def card_issue_page(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        refresh_expired_cards(db)
        hotel = load_hotel(db)
        eligible = list(
            db.scalars(
                select(Guest)
                .join(Room)
                .where(Guest.status == "checked_in", Guest.room_id.is_not(None))
                .order_by(Room.number.asc())
            ).all()
        )
        default_expiry = date.today() + timedelta(days=hotel.card_validity_days)
        return render(
            request,
            "card_issue.html",
            user=user,
            active="cards",
            db=db,
            guests=eligible,
            errors={},
            form={
                "guest_id": str(eligible[0].id) if eligible else "",
                "expires_at": default_expiry.isoformat(),
                "notes": "",
            },
            hotel=hotel,
            default_validity_days=hotel.card_validity_days,
        )

    @app.post("/cards/issue")
    async def card_issue_submit(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        guest_id = _safe_int(_form_text(form, "guest_id"))
        expires_raw = _form_text(form, "expires_at")
        expires_date = _parse_date(expires_raw)
        notes = _form_text(form, "notes")
        guest = db.get(Guest, guest_id) if guest_id else None
        room = db.get(Room, guest.room_id) if guest and guest.room_id else None
        errors: dict[str, str] = {}
        if guest is None:
            errors["guest_id"] = "Choose a checked-in guest."
        elif guest.status != "checked_in" or room is None:
            errors["guest_id"] = "The guest must be checked in and assigned to a room."
        if expires_date is None:
            errors["expires_at"] = "Choose a valid expiry date."
        elif expires_date < date.today():
            errors["expires_at"] = "Expiry date cannot be in the past."
        if len(notes) > 2000:
            errors["notes"] = "Notes must be 2,000 characters or fewer."
        if errors or guest is None or room is None or expires_date is None:
            eligible = list(
                db.scalars(
                    select(Guest)
                    .join(Room)
                    .where(Guest.status == "checked_in", Guest.room_id.is_not(None))
                    .order_by(Room.number.asc())
                ).all()
            )
            return render(
                request,
                "card_issue.html",
                user=user,
                active="cards",
                db=db,
                guests=eligible,
                errors=errors,
                form={
                    "guest_id": str(guest_id or ""),
                    "expires_at": expires_raw,
                    "notes": notes,
                },
                hotel=load_hotel(db),
                default_validity_days=load_hotel(db).card_validity_days,
            )
        card = issue_card(
            db,
            room=room,
            guest=guest,
            user=user,
            expires_at=card_expiry_from_date(expires_date),
            notes=notes or None,
            ip_address=client_ip(request),
        )
        _flash(
            request,
            f"Simulated card {card.card_number} was recorded. No physical card was written.",
        )
        return RedirectResponse(f"/cards/{card.id}", status_code=303)

    @app.get("/cards/{card_id}", response_class=HTMLResponse)
    def card_detail(
        request: Request,
        card_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        refresh_expired_cards(db)
        card = db.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Card not found.")
        replacement = db.get(Card, card.replaced_by_card_id) if card.replaced_by_card_id else None
        return render(
            request,
            "card_detail.html",
            user=user,
            active="cards",
            db=db,
            card=card,
            replacement=replacement,
            history=card_history(db, card.id),
        )

    @app.post("/cards/{card_id}/cancel")
    async def card_cancel(
        request: Request,
        card_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        card = db.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Card not found.")
        if card.status != "active":
            _flash(request, "Only an active card can be cancelled.", "warning")
            return RedirectResponse(f"/cards/{card.id}", status_code=303)
        cancel_card(db, card=card, user=user, ip_address=client_ip(request))
        _flash(request, f"Card {card.card_number} was cancelled.")
        return RedirectResponse(f"/cards/{card.id}", status_code=303)

    @app.post("/cards/{card_id}/replace")
    async def card_replace(
        request: Request,
        card_id: int,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        card = db.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Card not found.")
        if card.status not in {"active", "expired"}:
            _flash(request, "Only an active or expired card can be replaced.", "warning")
            return RedirectResponse(f"/cards/{card.id}", status_code=303)
        replacement_expiry = card.expires_at
        if card.status == "expired" or replacement_expiry <= datetime.now(UTC).replace(tzinfo=None):
            hotel = load_hotel(db)
            replacement_expiry = card_expiry_from_date(
                date.today() + timedelta(days=hotel.card_validity_days)
            )
        replacement = replace_card(
            db,
            card=card,
            user=user,
            ip_address=client_ip(request),
            expires_at=replacement_expiry,
        )
        _flash(
            request,
            f"Card {card.card_number} was replaced by {replacement.card_number} (simulation).",
        )
        return RedirectResponse(f"/cards/{replacement.id}", status_code=303)

    @app.get("/encoder", response_class=HTMLResponse)
    def encoder_page(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        return render(
            request,
            "encoder.html",
            user=user,
            active="encoder",
            db=db,
            encoder=app.state.encoder.status(),
            samples=app.state.encoder.sample_cards(),
            selected_sample="mifare_classic_1k",
        )

    @app.post("/encoder/check")
    async def encoder_check(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        status = await asyncio.to_thread(app.state.encoder.check)
        log_activity(
            db,
            user=user,
            action="encoder.check",
            description=(
                f"Checked encoder connection ({status['mode_label']}). "
                f"Result: {status['message']}"
            ),
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, status["message"], "success" if status["connected"] else "error")
        return RedirectResponse("/encoder", status_code=303)

    @app.post("/encoder/detect")
    async def encoder_detect(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        sample = _form_text(form, "sample") or "mifare_classic_1k"
        status = await asyncio.to_thread(app.state.encoder.detect, sample)
        card = status.get("card")
        description = (
            f"Detected {card['technology']} in read-only encoder simulation."
            if card
            else status["message"]
        )
        log_activity(
            db,
            user=user,
            action="encoder.detect",
            description=description,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, status["message"], "success" if status["card_detected"] else "warning")
        return RedirectResponse("/encoder", status_code=303)

    @app.get("/activity", response_class=HTMLResponse)
    def activity(
        request: Request,
        q: str = "",
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> Response:
        query = select(ActivityLog)
        if q.strip():
            needle = f"%{q.strip()}%"
            query = query.where(
                or_(
                    ActivityLog.action.ilike(needle),
                    ActivityLog.description.ilike(needle),
                )
            )
        entries = list(
            db.scalars(
                query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(
                    PAGE_SIZE
                )
            ).all()
        )
        return render(
            request,
            "activity.html",
            user=user,
            active="activity",
            db=db,
            entries=entries,
            q=q,
        )

    @app.get("/users", response_class=HTMLResponse)
    def users(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        users_list = list(db.scalars(select(User).order_by(User.full_name.asc())).all())
        return render(
            request,
            "users.html",
            user=user,
            active="users",
            db=db,
            users=users_list,
        )

    def user_form_response(
        request: Request,
        admin: User,
        db: Session,
        *,
        form: dict,
        errors: dict[str, str],
        mode: str,
        user_id: int | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "user_form.html",
            user=admin,
            active="users",
            db=db,
            form=form,
            errors=errors,
            mode=mode,
            user_id=user_id,
            roles=USER_ROLES,
            role_labels=USER_ROLE_LABELS,
        )

    @app.get("/users/new", response_class=HTMLResponse)
    def user_new(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        return user_form_response(
            request, user, db, form=_user_values(), errors={}, mode="new"
        )

    @app.post("/users/new")
    async def user_create(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values = _user_values()
        values.update(
            {
                "username": _form_text(form, "username").lower(),
                "email": _form_text(form, "email").lower(),
                "full_name": _form_text(form, "full_name"),
                "role": _form_text(form, "role"),
                "active": _form_bool(form, "active"),
            }
        )
        password = str(form.get("password", ""))
        confirmation = str(form.get("password_confirm", ""))
        errors: dict[str, str] = {}
        if not re.match(r"^[a-z0-9._-]{3,60}$", values["username"]):
            errors["username"] = "Use 3-60 lowercase letters, numbers, dots, dashes, or underscores."
        if db.scalar(
            select(func.count(User.id)).where(User.username == values["username"])
        ):
            errors["username"] = "That username is already in use."
        if not EMAIL_RE.match(values["email"]):
            errors["email"] = "Enter a valid email address."
        if db.scalar(select(func.count(User.id)).where(User.email == values["email"])):
            errors["email"] = "That email is already in use."
        if not values["full_name"]:
            errors["full_name"] = "Full name is required."
        if values["role"] not in USER_ROLES:
            errors["role"] = "Choose a valid role."
        password_problems = password_errors(password, confirmation)
        if password_problems:
            errors["password"] = " ".join(password_problems)
        if errors:
            return user_form_response(
                request, user, db, form=values, errors=errors, mode="new"
            )
        account = User(
            username=values["username"],
            email=values["email"],
            full_name=values["full_name"],
            password_hash=hash_password(password),
            role=values["role"],
            active=values["active"],
        )
        db.add(account)
        db.flush()
        log_activity(
            db,
            user=user,
            action="user.create",
            description=f"Created {USER_ROLE_LABELS[account.role]} account for {account.full_name}.",
            entity_type="user",
            entity_id=account.id,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, f"User {account.full_name} was created.")
        return RedirectResponse("/users", status_code=303)

    @app.get("/users/{user_id}/edit", response_class=HTMLResponse)
    def user_edit(
        request: Request,
        user_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        account = db.get(User, user_id)
        if account is None:
            raise HTTPException(status_code=404, detail="User not found.")
        return user_form_response(
            request,
            user,
            db,
            form=_user_values(account),
            errors={},
            mode="edit",
            user_id=account.id,
        )

    @app.post("/users/{user_id}/edit")
    async def user_update(
        request: Request,
        user_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        account = db.get(User, user_id)
        if account is None:
            raise HTTPException(status_code=404, detail="User not found.")
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values = _user_values(account)
        values.update(
            {
                "username": _form_text(form, "username").lower(),
                "email": _form_text(form, "email").lower(),
                "full_name": _form_text(form, "full_name"),
                "role": _form_text(form, "role"),
                "active": _form_bool(form, "active"),
            }
        )
        password = str(form.get("password", ""))
        confirmation = str(form.get("password_confirm", ""))
        errors: dict[str, str] = {}
        if not re.match(r"^[a-z0-9._-]{3,60}$", values["username"]):
            errors["username"] = "Use 3-60 lowercase letters, numbers, dots, dashes, or underscores."
        if db.scalar(
            select(func.count(User.id)).where(
                User.username == values["username"], User.id != account.id
            )
        ):
            errors["username"] = "That username is already in use."
        if not EMAIL_RE.match(values["email"]):
            errors["email"] = "Enter a valid email address."
        if db.scalar(
            select(func.count(User.id)).where(
                User.email == values["email"], User.id != account.id
            )
        ):
            errors["email"] = "That email is already in use."
        if not values["full_name"]:
            errors["full_name"] = "Full name is required."
        if values["role"] not in USER_ROLES:
            errors["role"] = "Choose a valid role."
        if password:
            password_problems = password_errors(password, confirmation)
            if password_problems:
                errors["password"] = " ".join(password_problems)
        if account.id == user.id and not values["active"]:
            errors["active"] = "You cannot deactivate your own account."
        if account.role == "administrator" and (
            values["role"] != "administrator" or not values["active"]
        ):
            admin_count = db.scalar(
                select(func.count(User.id)).where(
                    User.role == "administrator", User.active.is_(True)
                )
            )
            if (admin_count or 0) <= 1:
                errors["role"] = "At least one active administrator is required."
        if errors:
            return user_form_response(
                request,
                user,
                db,
                form=values,
                errors=errors,
                mode="edit",
                user_id=account.id,
            )
        account.username = values["username"]
        account.email = values["email"]
        account.full_name = values["full_name"]
        account.role = values["role"]
        account.active = values["active"]
        if password:
            account.password_hash = hash_password(password)
        log_activity(
            db,
            user=user,
            action="user.update",
            description=f"Updated account for {account.full_name}.",
            entity_type="user",
            entity_id=account.id,
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, f"User {account.full_name} was updated.")
        return RedirectResponse("/users", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        hotel = load_hotel(db)
        return render(
            request,
            "settings.html",
            user=user,
            active="settings",
            db=db,
            form={
                "hotel_name": hotel.name,
                "hotel_address": hotel.address,
                "hotel_phone": hotel.phone,
                "hotel_timezone": hotel.timezone,
                "card_validity_days": str(hotel.card_validity_days),
            },
            errors={},
            encoder=app.state.encoder.status(),
        )

    @app.post("/settings")
    async def settings_update(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ) -> Response:
        form = await request.form()
        check_csrf(request, _form_text(form, "csrf_token"))
        values = {
            "hotel_name": _form_text(form, "hotel_name"),
            "hotel_address": _form_text(form, "hotel_address"),
            "hotel_phone": _form_text(form, "hotel_phone"),
            "hotel_timezone": _form_text(form, "hotel_timezone"),
            "card_validity_days": _form_text(form, "card_validity_days"),
        }
        errors: dict[str, str] = {}
        if not values["hotel_name"]:
            errors["hotel_name"] = "Hotel name is required."
        if len(values["hotel_name"]) > 120:
            errors["hotel_name"] = "Hotel name must be 120 characters or fewer."
        try:
            validity = int(values["card_validity_days"])
            if validity < 1 or validity > 3650:
                raise ValueError
        except ValueError:
            errors["card_validity_days"] = "Card validity must be between 1 and 3,650 days."
        if not values["hotel_timezone"]:
            errors["hotel_timezone"] = "Timezone is required."
        if errors:
            return render(
                request,
                "settings.html",
                user=user,
                active="settings",
                db=db,
                form=values,
                errors=errors,
                encoder=app.state.encoder.status(),
            )
        save_hotel(db, values)
        log_activity(
            db,
            user=user,
            action="settings.update",
            description="Updated hotel information and card preferences.",
            ip_address=client_ip(request),
        )
        db.commit()
        _flash(request, "Settings were saved.")
        return RedirectResponse("/settings", status_code=303)

    return app
