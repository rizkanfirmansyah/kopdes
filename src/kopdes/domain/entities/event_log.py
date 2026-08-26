from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from kopdes.shared.enums import EventLevel


@dataclass(slots=True)
class EventLog:
    id: str
    profile_id: str | None
    level: EventLevel
    event_type: str
    message: str
    details: str | None = None
    created_at: datetime | None = None
