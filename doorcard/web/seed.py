from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ActivityLog, Card, Guest, Room, Setting, User
from .security import hash_password

DEMO_ADMIN_EMAIL = "admin@horizon.test"
DEMO_ADMIN_PASSWORD = "Admin!23456"
DEMO_RECEPTION_EMAIL = "reception@horizon.test"
DEMO_RECEPTION_PASSWORD = "Reception!23456"


def _at(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59))


def seed_demo(db: Session, hotel_name: str = "The Horizon Grand") -> bool:
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        return False

    admin = User(
        username="admin",
        email=DEMO_ADMIN_EMAIL,
        full_name="Avery Morgan",
        password_hash=hash_password(DEMO_ADMIN_PASSWORD),
        role="administrator",
    )
    reception = User(
        username="reception",
        email=DEMO_RECEPTION_EMAIL,
        full_name="Jordan Lee",
        password_hash=hash_password(DEMO_RECEPTION_PASSWORD),
        role="receptionist",
    )
    db.add_all([admin, reception])
    db.flush()

    rooms = [
        Room(number="101", room_type="Standard King", floor=1, status="occupied"),
        Room(number="102", room_type="Deluxe King", floor=1, status="occupied"),
        Room(number="103", room_type="Standard Twin", floor=1, status="available"),
        Room(number="104", room_type="Executive Suite", floor=2, status="available"),
        Room(number="105", room_type="Family Suite", floor=2, status="maintenance"),
        Room(number="106", room_type="Accessible Room", floor=2, status="available"),
        Room(number="107", room_type="Deluxe Twin", floor=3, status="available"),
        Room(number="108", room_type="Standard King", floor=3, status="available"),
    ]
    db.add_all(rooms)
    db.flush()

    today = date.today()
    guests = [
        Guest(
            full_name="Elena Vasquez",
            email="elena.vasquez@example.test",
            phone="+1 555 0101",
            document_id="P-884201",
            room_id=rooms[0].id,
            check_in=today - timedelta(days=1),
            check_out=today + timedelta(days=2),
            status="checked_in",
        ),
        Guest(
            full_name="Marcus Chen",
            email="marcus.chen@example.test",
            phone="+1 555 0102",
            document_id="P-884202",
            room_id=rooms[1].id,
            check_in=today,
            check_out=today + timedelta(days=3),
            status="checked_in",
        ),
        Guest(
            full_name="Priya Nair",
            email="priya.nair@example.test",
            phone="+1 555 0103",
            document_id="P-884203",
            room_id=rooms[2].id,
            check_in=today + timedelta(days=2),
            check_out=today + timedelta(days=5),
            status="reserved",
        ),
        Guest(
            full_name="Thomas Reed",
            email="thomas.reed@example.test",
            phone="+1 555 0104",
            document_id="P-884204",
            room_id=rooms[2].id,
            check_in=today - timedelta(days=4),
            check_out=today - timedelta(days=1),
            status="checked_out",
        ),
    ]
    db.add_all(guests)
    db.flush()

    cards = [
        Card(
            card_number="SIM-DEMO-1001",
            room_id=rooms[0].id,
            guest_id=guests[0].id,
            status="active",
            expires_at=_at(today + timedelta(days=2)),
            issued_by_id=reception.id,
            notes="Demo active card.",
        ),
        Card(
            card_number="SIM-DEMO-1002",
            room_id=rooms[1].id,
            guest_id=guests[1].id,
            status="active",
            expires_at=_at(today + timedelta(days=3)),
            issued_by_id=admin.id,
            notes="Demo active card.",
        ),
        Card(
            card_number="SIM-DEMO-0998",
            room_id=rooms[2].id,
            guest_id=guests[3].id,
            status="expired",
            expires_at=_at(today - timedelta(days=1)),
            issued_by_id=reception.id,
            notes="Demo expired card.",
        ),
        Card(
            card_number="SIM-DEMO-0997",
            room_id=rooms[2].id,
            guest_id=guests[2].id,
            status="cancelled",
            expires_at=_at(today + timedelta(days=5)),
            issued_by_id=admin.id,
            notes="Demo cancelled card.",
        ),
    ]
    db.add_all(cards)

    settings = {
        "hotel_name": hotel_name,
        "hotel_address": "1 Marina Boulevard, Harbor District",
        "hotel_phone": "+1 (555) 010-4400",
        "hotel_timezone": "UTC",
        "card_validity_days": "3",
    }
    for key, value in settings.items():
        db.add(Setting(key=key, value=value))

    db.add_all(
        [
            ActivityLog(
                user_id=admin.id,
                action="system.seed",
                description="Demo hotel data was created for local evaluation.",
                ip_address="127.0.0.1",
            ),
            ActivityLog(
                user_id=reception.id,
                action="card.issue.simulated",
                description="Issued demo card SIM-DEMO-1001 for room 101.",
                entity_type="card",
                entity_id=cards[0].id,
                ip_address="127.0.0.1",
            ),
            ActivityLog(
                user_id=admin.id,
                action="card.issue.simulated",
                description="Issued demo card SIM-DEMO-1002 for room 102.",
                entity_type="card",
                entity_id=cards[1].id,
                ip_address="127.0.0.1",
            ),
        ]
    )
    db.commit()
    return True
