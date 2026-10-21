from __future__ import annotations

ROOM_TYPES = (
    "Standard King",
    "Standard Twin",
    "Deluxe King",
    "Deluxe Twin",
    "Executive Suite",
    "Family Suite",
    "Accessible Room",
)

ROOM_STATUSES = ("available", "occupied", "maintenance", "out_of_service")
ROOM_STATUS_LABELS = {
    "available": "Available",
    "occupied": "Occupied",
    "maintenance": "Maintenance",
    "out_of_service": "Out of service",
}

GUEST_STATUSES = ("reserved", "checked_in", "checked_out", "cancelled")
GUEST_STATUS_LABELS = {
    "reserved": "Reserved",
    "checked_in": "Checked in",
    "checked_out": "Checked out",
    "cancelled": "Cancelled",
}

CARD_STATUSES = ("active", "expired", "cancelled", "replaced")
CARD_STATUS_LABELS = {
    "active": "Active",
    "expired": "Expired",
    "cancelled": "Cancelled",
    "replaced": "Replaced",
}

USER_ROLES = ("administrator", "receptionist")
USER_ROLE_LABELS = {
    "administrator": "Administrator",
    "receptionist": "Receptionist",
}

STATUS_TONES = {
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
}

ENCODER_MODES = ("simulated", "pcsc", "vendor")


def label_for(value: str) -> str:
    return {
        **ROOM_STATUS_LABELS,
        **GUEST_STATUS_LABELS,
        **CARD_STATUS_LABELS,
        **USER_ROLE_LABELS,
    }.get(value, value.replace("_", " ").title())
