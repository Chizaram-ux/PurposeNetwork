"""Postgres tables.

Two ideas shape this schema:

* A round is stored as real groups, not as the flat list of `"A | B"` pair keys
  that history.json used. A group of three is one row with three members, so the
  pairings page can show what actually happened.
* "Who has already met" is therefore *derived* from group membership rather than
  kept in a second table. There is nothing to fall out of step.

The list columns are Postgres arrays in production and JSON under SQLite, which
is what lets the test suite run without a database server.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Postgres gets text[]; SQLite gets a JSON array. Both read back as a list.
StringList = ARRAY(Text()).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class Participant(Base):
    """A person on the roster.

    `name` is unique because pair identity is name-based throughout the engine
    (see pair.pair_key), so two people sharing a name would share a history.
    `availability_raw` keeps whatever wording arrived, form answer or slot grid,
    while `slots` holds the normalised `Mon AM`-style codes used for matching.
    """

    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    entity: Mapped[str] = mapped_column(Text, nullable=False, default="")
    team: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chat_format: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Used only to build the invitation payload the mail flow sends. It is never
    # returned by the API, because the pairings page is unauthenticated.
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    availability_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    slots: Mapped[List[str]] = mapped_column(StringList, nullable=False, default=list)
    topics: Mapped[List[str]] = mapped_column(StringList, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class Round(Base):
    """One completed round of pairings."""

    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ran_on: Mapped[date] = mapped_column(Date, nullable=False)
    require_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seed: Mapped[Optional[int]] = mapped_column(Integer)
    total_score: Mapped[Optional[float]] = mapped_column(Float)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Where the round came from: "github-action", "cli" or "import".
    source: Mapped[str] = mapped_column(Text, nullable=False, default="cli")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    groups: Mapped[List["RoundGroup"]] = relationship(
        back_populates="round",
        cascade="all, delete-orphan",
        order_by="RoundGroup.position",
    )
    unmatched: Mapped[List["RoundUnmatched"]] = relationship(
        back_populates="round", cascade="all, delete-orphan"
    )


class RoundGroup(Base):
    """A coffee chat: two people, or three when the headcount is odd.

    The score and its reasons are stored so the page can answer "why these two",
    which is the same information `pair.py --explain` prints.
    """

    __tablename__ = "round_groups"
    __table_args__ = (UniqueConstraint("round_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    shared_slots: Mapped[List[str]] = mapped_column(StringList, nullable=False, default=list)
    shared_topics: Mapped[List[str]] = mapped_column(StringList, nullable=False, default=list)
    formats: Mapped[List[str]] = mapped_column(StringList, nullable=False, default=list)
    score: Mapped[Optional[float]] = mapped_column(Float)
    score_reasons: Mapped[List[str]] = mapped_column(StringList, nullable=False, default=list)

    round: Mapped[Round] = relationship(back_populates="groups")
    members: Mapped[List["GroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMember(Base):
    """Who was in a group. Self-joining this table is what yields met-before."""

    __tablename__ = "round_group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("round_groups.id", ondelete="CASCADE"), primary_key=True
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True
    )

    group: Mapped[RoundGroup] = relationship(back_populates="members")
    participant: Mapped[Participant] = relationship()


class RoundUnmatched(Base):
    """Someone the round could not place, usually for want of a shared slot."""

    __tablename__ = "round_unmatched"

    round_id: Mapped[int] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), primary_key=True
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True
    )

    round: Mapped[Round] = relationship(back_populates="unmatched")
    participant: Mapped[Participant] = relationship()
