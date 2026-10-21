from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .constants import ENCODER_MODES

LOGGER = logging.getLogger("doorcard.web")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class WebSettings:
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'doorcard-web.db').as_posix()}"
    secret_key: str = ""
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    secure_cookies: bool = False
    session_max_age: int = 8 * 60 * 60
    encoder_mode: str = "simulated"
    seed_demo: bool = True
    hotel_name: str = "The Horizon Grand"
    allowed_hosts: tuple[str, ...] = ("*",)
    login_max_attempts: int = 5
    login_window_seconds: int = 15 * 60
    database_engine_options: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> WebSettings:
        environment = os.environ.get("DOORCARD_WEB_ENV", "development").strip().lower()
        secret = os.environ.get("DOORCARD_WEB_SECRET", "").strip()
        if not secret:
            if environment == "production":
                raise RuntimeError(
                    "DOORCARD_WEB_SECRET must be set before running in production."
                )
            secret = secrets.token_urlsafe(48)
            LOGGER.warning(
                "DOORCARD_WEB_SECRET is not set; generated an ephemeral session secret. "
                "Set it in .env to keep sessions valid across restarts."
            )

        encoder_mode = os.environ.get("DOORCARD_ENCODER_MODE", "simulated").strip().lower()
        if encoder_mode not in ENCODER_MODES:
            LOGGER.warning("Unknown DOORCARD_ENCODER_MODE=%s; using simulated.", encoder_mode)
            encoder_mode = "simulated"

        allowed_hosts_raw = (
            os.environ.get("DOORCARD_WEB_ALLOWED_HOSTS", "").strip()
            or os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
            or "*"
        )
        allowed_hosts = tuple(
            item.strip() for item in allowed_hosts_raw.split(",") if item.strip()
        ) or ("*",)

        return cls(
            database_url=os.environ.get(
                "DOORCARD_DATABASE_URL",
                f"sqlite:///{(PROJECT_ROOT / 'data' / 'doorcard-web.db').as_posix()}",
            ).strip(),
            secret_key=secret,
            environment=environment,
            host=os.environ.get("DOORCARD_WEB_HOST", "127.0.0.1").strip(),
            port=_env_int("DOORCARD_WEB_PORT", _env_int("PORT", 8000)),
            secure_cookies=_env_bool(
                "DOORCARD_WEB_SECURE_COOKIE", environment == "production"
            ),
            session_max_age=_env_int("DOORCARD_WEB_SESSION_MAX_AGE", 8 * 60 * 60),
            encoder_mode=encoder_mode,
            seed_demo=_env_bool("DOORCARD_SEED_DEMO", environment != "production"),
            hotel_name=os.environ.get("DOORCARD_HOTEL_NAME", "The Horizon Grand").strip(),
            allowed_hosts=allowed_hosts,
            login_max_attempts=_env_int("DOORCARD_LOGIN_MAX_ATTEMPTS", 5),
            login_window_seconds=_env_int("DOORCARD_LOGIN_WINDOW_SECONDS", 15 * 60),
        )
