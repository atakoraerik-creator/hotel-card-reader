from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import or_, select

from .config import WebSettings
from .db import Database
from .models import User
from .security import hash_password, password_errors
from .seed import seed_demo


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        errors = password_errors(password, confirmation)
        if not errors:
            return password
        for error in errors:
            print(f"  {error}")


def _ensure_database(settings: WebSettings) -> Database:
    database = Database(settings.database_url, settings.database_engine_options)
    database.create_all()
    return database


def _create_admin(settings: WebSettings, args: argparse.Namespace) -> int:
    database = _ensure_database(settings)
    with database.session() as db:
        existing = db.scalar(
            select(User).where(
                or_(User.email == args.email.lower(), User.username == args.username.lower())
            )
        )
        if existing is not None:
            print("A user with that email or username already exists.", file=sys.stderr)
            return 2
        password = _prompt_password()
        db.add(
            User(
                username=args.username.lower(),
                email=args.email.lower(),
                full_name=args.name,
                password_hash=hash_password(password),
                role="administrator",
                active=True,
            )
        )
        db.commit()
    print(f"Administrator {args.username} created.")
    return 0


def _reset_password(settings: WebSettings, args: argparse.Namespace) -> int:
    database = _ensure_database(settings)
    with database.session() as db:
        user = db.scalar(
            select(User).where(
                or_(User.email == args.email.lower(), User.username == args.email.lower())
            )
        )
        if user is None:
            print("User not found.", file=sys.stderr)
            return 2
        user.password_hash = hash_password(_prompt_password())
        db.commit()
    print(f"Password updated for {user.username}.")
    return 0


def _init_db(settings: WebSettings, args: argparse.Namespace) -> int:
    del args
    database = _ensure_database(settings)
    if settings.seed_demo:
        with database.session() as db:
            created = seed_demo(db, hotel_name=settings.hotel_name)
        print("Demo data seeded." if created else "Database already contains users.")
    print(f"Database ready: {settings.database_url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m doorcard.web.manage",
        description="Database and administrator management for the web interface.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create tables and optional demo data.")
    init_parser.set_defaults(handler=_init_db)

    admin_parser = subparsers.add_parser("create-admin", help="Create an administrator account.")
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--name", required=True)
    admin_parser.set_defaults(handler=_create_admin)

    reset_parser = subparsers.add_parser("reset-password", help="Reset a user's password.")
    reset_parser.add_argument("--email", required=True)
    reset_parser.set_defaults(handler=_reset_password)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = WebSettings.from_env()
    try:
        return int(args.handler(settings, args))
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
