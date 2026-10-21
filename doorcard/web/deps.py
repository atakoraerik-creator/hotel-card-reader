from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .models import User


class LoginRequired(Exception):
    pass


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.session() as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        parsed_id = int(user_id)
    except (TypeError, ValueError):
        request.session.clear()
        return None
    user = db.get(User, parsed_id)
    if user is None or not user.active:
        request.session.clear()
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "administrator":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user
