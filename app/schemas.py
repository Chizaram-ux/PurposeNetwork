"""Request and response shapes.

Availability is accepted either as slot codes from the sign-up grid or as raw
form wording, and is always normalised before it is stored.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator

import pair
from app import adapters, config, models


class Options(BaseModel):
    """Everything the sign-up form needs in order to render itself."""

    entities: List[str]
    formats: List[str]
    slots: List[str]
    timezone_label: str
    timezone_short: str
    topic_suggestions: List[str]

    @classmethod
    def build(cls) -> "Options":
        return cls(
            entities=list(config.ENTITIES),
            formats=list(config.FORMATS),
            slots=list(pair.ALL_SLOTS),
            timezone_label=config.TIMEZONE_LABEL,
            timezone_short=config.TIMEZONE_SHORT,
            topic_suggestions=list(config.TOPIC_SUGGESTIONS),
        )


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    entity: str = Field(min_length=1, max_length=120)
    team: str = Field(default="", max_length=120)
    chat_format: str = Field(default="Online", max_length=40)
    # Optional: a round still runs without it, and anyone missing an address is
    # listed under needsEmailAddress in the invitation payload.
    email: str = Field(default="", max_length=254)
    availability: Union[List[str], str] = ""
    topics: Union[List[str], str] = Field(default_factory=list)

    @field_validator("name", "entity", "team", "chat_format", "email")
    @classmethod
    def tidy(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def plausible_email(cls, value: str) -> str:
        """A light check only: catching typos is not worth a new dependency."""
        if value and ("@" not in value or " " in value):
            raise ValueError("must be an email address")
        return value

    @field_validator("name", "entity")
    @classmethod
    def not_blank(cls, value: str) -> str:
        """Runs after `tidy`, so a field of spaces is rejected rather than stored empty."""
        if not value:
            raise ValueError("must not be blank")
        return value

    @property
    def normalised_format(self) -> str:
        """Match a known format's capitalisation; otherwise keep what was sent."""
        for known in config.FORMATS:
            if known.lower() == self.chat_format.lower():
                return known
        return self.chat_format

    @property
    def slots(self) -> List[str]:
        return adapters.normalise_slots(self.availability)

    @property
    def normalised_topics(self) -> List[str]:
        return adapters.normalise_topics(self.topics)


class ParticipantOut(BaseModel):
    """Deliberately without the email address.

    Everything the API serves is readable by anyone who can reach the page, so
    addresses stay server-side. `has_email` is enough to spot a gap in the roster
    without publishing a list of colleagues' addresses.
    """

    id: int
    name: str
    entity: str
    team: str
    chat_format: str
    has_email: bool
    slots: List[str]
    topics: List[str]
    active: bool

    @classmethod
    def of(cls, row: models.Participant) -> "ParticipantOut":
        return cls(
            id=row.id,
            name=row.name,
            entity=row.entity,
            team=row.team,
            chat_format=row.chat_format,
            has_email=bool(row.email),
            slots=list(row.slots or ()),
            topics=list(row.topics or ()),
            active=row.active,
        )


class MemberOut(BaseModel):
    """Also without the email address, for the same reason as ParticipantOut."""

    name: str
    entity: str
    team: str
    chat_format: str
    slots: List[str]

    @classmethod
    def of(cls, row: models.Participant) -> "MemberOut":
        return cls(
            name=row.name,
            entity=row.entity,
            team=row.team,
            chat_format=row.chat_format,
            slots=list(row.slots or ()),
        )


class GroupOut(BaseModel):
    position: int
    members: List[MemberOut]
    shared_slots: List[str]
    shared_topics: List[str]
    formats: List[str]
    score: Optional[float] = None
    score_reasons: List[str] = Field(default_factory=list)

    @classmethod
    def of(cls, row: models.RoundGroup) -> "GroupOut":
        return cls(
            position=row.position,
            members=[MemberOut.of(member.participant) for member in row.members],
            shared_slots=list(row.shared_slots or ()),
            shared_topics=list(row.shared_topics or ()),
            formats=list(row.formats or ()),
            score=row.score,
            score_reasons=list(row.score_reasons or ()),
        )


class RoundOut(BaseModel):
    id: int
    ran_on: date
    require_overlap: bool
    headcount: int
    group_count: int
    total_score: Optional[float] = None
    groups: List[GroupOut]
    unmatched: List[str]

    @classmethod
    def of(cls, row: models.Round) -> "RoundOut":
        return cls(
            id=row.id,
            ran_on=row.ran_on,
            require_overlap=row.require_overlap,
            headcount=row.headcount,
            group_count=len(row.groups),
            total_score=row.total_score,
            groups=[GroupOut.of(group) for group in row.groups],
            unmatched=sorted(entry.participant.name for entry in row.unmatched),
        )


class RoundSummary(BaseModel):
    id: int
    ran_on: date
    headcount: int
    group_count: int
    unmatched_count: int

    @classmethod
    def of(cls, row: models.Round, counts) -> "RoundSummary":
        groups, unmatched = counts
        return cls(
            id=row.id,
            ran_on=row.ran_on,
            headcount=row.headcount,
            group_count=groups,
            unmatched_count=unmatched,
        )
