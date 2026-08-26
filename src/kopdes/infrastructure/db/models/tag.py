from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kopdes.infrastructure.db.base import Base


class TagModel(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    profiles: Mapped[list["ConnectionProfileModel"]] = relationship(
        secondary="profile_tags",
        back_populates="tags",
    )


class ProfileTagModel(Base):
    __tablename__ = "profile_tags"

    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("connection_profiles.id"),
        primary_key=True,
    )
    tag_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tags.id"),
        primary_key=True,
    )
