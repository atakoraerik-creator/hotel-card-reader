from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .constants import CARD_STATUS_LABELS, GUEST_STATUS_LABELS, ROOM_STATUS_LABELS
from .models import ActivityLog, Card, Guest, Room, Setting, User, utcnow

DEFAULT_SETTINGS = {
    "hotel_name": "The Horizon Grand",
    "hotel_address": "1 Marina Boulevard, Harbor District",
    "hotel_phone": "+1 (555) 010-4400",
    "hotel_timezone": "UTC",
    "card_validity_days": "3",
}


@dataclass(frozen=True)
class HotelInfo:
    name: str
    address: str
    phone: str
    timezone: str
    card_validity_days: int


@dataclass(frozen=True)
class DashboardStats:
    total_rooms: int
    occupied_rooms: int
    available_rooms: int
    maintenance_rooms: int
    active_cards: int
    expired_cards: int
    occupancy_pct: int


def load_hotel(db: Session) -> HotelInfo:
    values = dict(DEFAULT_SETTINGS)
    for setting in db.scalars(select(Setting)).all():
        values[setting.key] = setting.value
    try:
        validity = max(1, min(3650, int(values["card_validity_days"])))
    except ValueError:
        validity = 3
    return HotelInfo(
        name=values["hotel_name"],
        address=values["hotel_address"],
        phone=values["hotel_phone"],
        timezone=values["hotel_timezone"],
        card_validity_days=validity,
    )


def save_hotel(db: Session, values: dict[str, str]) -> None:
    for key, value in values.items():
        setting = db.get(Setting, key)
        if setting is None:
            db.add(Setting(key=key, value=value))
        else:
            setting.value = value


def log_activity(
    db: Session,
    *,
    user: User | None,
    action: str,
    description: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    ip_address: str | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry


def refresh_expired_cards(db: Session) -> None:
    db.execute(
        update(Card)
        .where(Card.status == "active", Card.expires_at < utcnow())
        .values(status="expired")
    )
    db.commit()


def dashboard_stats(db: Session) -> DashboardStats:
    refresh_expired_cards(db)
    room_counts = dict(
        db.execute(select(Room.status, func.count(Room.id)).group_by(Room.status)).all()
    )
    total = sum(room_counts.values())
    occupied = room_counts.get("occupied", 0)
    active = db.scalar(
        select(func.count(Card.id)).where(
            Card.status == "active", Card.expires_at >= utcnow()
        )
    ) or 0
    expired = db.scalar(
        select(func.count(Card.id)).where(Card.status == "expired")
    ) or 0
    return DashboardStats(
        total_rooms=total,
        occupied_rooms=occupied,
        available_rooms=room_counts.get("available", 0),
        maintenance_rooms=room_counts.get("maintenance", 0)
        + room_counts.get("out_of_service", 0),
        active_cards=active,
        expired_cards=expired,
        occupancy_pct=round((occupied / total) * 100) if total else 0,
    )


def recent_activity(db: Session, limit: int = 8) -> list[ActivityLog]:
    return list(
        db.scalars(
            select(ActivityLog)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(limit)
        ).all()
    )


def expiring_cards(db: Session, days: int = 3) -> list[Card]:
    cutoff = utcnow() + timedelta(days=days)
    return list(
        db.scalars(
            select(Card)
            .where(
                Card.status == "active",
                Card.expires_at >= utcnow(),
                Card.expires_at <= cutoff,
            )
            .order_by(Card.expires_at.asc())
            .limit(8)
        ).all()
    )


def recalculate_room_status(db: Session, room_id: int | None) -> None:
    if room_id is None:
        return
    room = db.get(Room, room_id)
    if room is None or room.status in {"maintenance", "out_of_service"}:
        return
    occupied = db.scalar(
        select(func.count(Guest.id)).where(
            Guest.room_id == room_id, Guest.status == "checked_in"
        )
    )
    room.status = "occupied" if occupied else "available"


def card_expiry_from_date(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59))


def next_card_number(db: Session) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    for _ in range(20):
        candidate = f"SIM-{day}-{secrets.token_hex(2).upper()}"
        if not db.scalar(select(func.count(Card.id)).where(Card.card_number == candidate)):
            return candidate
    return f"SIM-{day}-{secrets.token_hex(4).upper()}"


def issue_card(
    db: Session,
    *,
    room: Room,
    guest: Guest,
    user: User,
    expires_at: datetime,
    notes: str | None,
    ip_address: str | None,
) -> Card:
    card = Card(
        card_number=next_card_number(db),
        room_id=room.id,
        guest_id=guest.id,
        status="active",
        expires_at=expires_at,
        issued_by_id=user.id,
        notes=notes,
    )
    db.add(card)
    db.flush()
    log_activity(
        db,
        user=user,
        action="card.issue.simulated",
        description=(
            f"Created simulated card {card.card_number} for room {room.number} "
            f"and guest {guest.full_name}. No hardware write was performed."
        ),
        entity_type="card",
        entity_id=card.id,
        ip_address=ip_address,
    )
    db.commit()
    return card


def cancel_card(
    db: Session, *, card: Card, user: User, ip_address: str | None
) -> None:
    card.status = "cancelled"
    log_activity(
        db,
        user=user,
        action="card.cancel",
        description=f"Cancelled card {card.card_number} for room {card.room.number}.",
        entity_type="card",
        entity_id=card.id,
        ip_address=ip_address,
    )
    db.commit()


def replace_card(
    db: Session,
    *,
    card: Card,
    user: User,
    ip_address: str | None,
    expires_at: datetime | None = None,
) -> Card:
    replacement = Card(
        card_number=next_card_number(db),
        room_id=card.room_id,
        guest_id=card.guest_id,
        status="active",
        expires_at=expires_at or card.expires_at,
        issued_by_id=user.id,
        notes=f"Replacement for {card.card_number}.",
    )
    db.add(replacement)
    db.flush()
    card.status = "replaced"
    card.replaced_by_card_id = replacement.id
    log_activity(
        db,
        user=user,
        action="card.replace",
        description=(
            f"Replaced card {card.card_number} with {replacement.card_number} for "
            f"room {card.room.number}. No hardware write was performed."
        ),
        entity_type="card",
        entity_id=card.id,
        ip_address=ip_address,
    )
    db.commit()
    return replacement


def card_history(db: Session, card_id: int) -> list[ActivityLog]:
    return list(
        db.scalars(
            select(ActivityLog)
            .where(ActivityLog.entity_type == "card", ActivityLog.entity_id == card_id)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        ).all()
    )


def status_label(value: str) -> str:
    return {
        **ROOM_STATUS_LABELS,
        **GUEST_STATUS_LABELS,
        **CARD_STATUS_LABELS,
    }.get(value, value.replace("_", " ").title())
