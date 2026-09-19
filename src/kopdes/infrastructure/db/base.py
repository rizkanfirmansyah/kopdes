from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Return timezone-aware UTC for application-managed timestamps."""
    return datetime.now(timezone.utc)
