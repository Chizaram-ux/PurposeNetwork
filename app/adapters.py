"""The joins between the database and the pairing engine.

Nothing here changes how pairing works. `pair.py` asks a History two questions
and takes a list of Participants; this module answers those questions from
Postgres and turns rows into Participants, then writes a finished round back.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Set, Union

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

import pair
from app import models

# ------------------------------------------------------------------ parsing --


def normalise_slots(availability: Union[Iterable[str], str]) -> List[str]:
    """Slot codes from either a checkbox grid or raw Microsoft Forms wording.

    The grid already sends `Mon AM`, but running everything through FormAnswers
    means the old free-text answers keep working unchanged.
    """
    raw = availability if isinstance(availability, str) else ";".join(availability)
    return list(pair.FormAnswers.slots(raw))


def normalise_topics(topics: Union[Iterable[str], str]) -> List[str]:
    raw = topics if isinstance(topics, str) else ";".join(topics)
    return list(pair.FormAnswers.values(raw))


def as_raw_text(value: Union[Iterable[str], str]) -> str:
    return value if isinstance(value, str) else "; ".join(value)


# ------------------------------------------------------------- the roster ---


def to_participant(row: models.Participant) -> pair.Participant:
    """A database row as the value object the engine expects."""
    return pair.Participant(
        name=row.name,
        entity=row.entity,
        team=row.team,
        chat_format=row.chat_format,
        email=row.email,
        slots=frozenset(row.slots or ()),
        topics=tuple(row.topics or ()),
    )


def active_participants(session: Session) -> List[pair.Participant]:
    rows = session.scalars(
        select(models.Participant)
        .where(models.Participant.active.is_(True))
        .order_by(models.Participant.name)
    ).all()
    return [to_participant(row) for row in rows]


def names_by_id(session: Session) -> Dict[int, str]:
    """Every participant, including retired ones - old pairs still count."""
    return dict(session.execute(select(models.Participant.id, models.Participant.name)).all())


def ids_by_name(session: Session) -> Dict[str, int]:
    return {name: pid for pid, name in names_by_id(session).items()}


# ------------------------------------------------------------------ history --


def _recent_round_ids(session: Session, limit: int = pair.RECENT_ROUNDS) -> List[int]:
    return list(
        session.scalars(
            select(models.Round.id)
            .order_by(models.Round.ran_on.desc(), models.Round.id.desc())
            .limit(limit)
        ).all()
    )


def _pair_keys(session: Session, names: Dict[int, str],
               round_ids: Optional[Sequence[int]] = None) -> Set[str]:
    """Pair keys for everyone who has shared a group.

    A self-join on membership gives each unordered pair once, so a group of
    three yields its three pairs without any special handling.
    """
    left = aliased(models.GroupMember)
    right = aliased(models.GroupMember)
    query = select(left.participant_id, right.participant_id).join(
        right,
        and_(left.group_id == right.group_id, left.participant_id < right.participant_id),
    )
    if round_ids is not None:
        if not round_ids:
            return set()
        query = query.join(models.RoundGroup, models.RoundGroup.id == left.group_id).where(
            models.RoundGroup.round_id.in_(round_ids)
        )
    return {
        key_for_names(names[a], names[b])
        for a, b in session.execute(query).all()
        if a in names and b in names
    }


def all_pair_keys(session: Session) -> Set[str]:
    """Every connection made so far, across all rounds."""
    return _pair_keys(session, names_by_id(session))


def key_for_names(a: str, b: str) -> str:
    """The engine's own key format, so both sides always agree."""
    return pair.pair_key(pair.Participant(name=a), pair.Participant(name=b))


class DatabaseHistory(pair.History):
    """History read from the round tables instead of history.json.

    Only the read half is needed: writing a round *is* how history is recorded,
    so `record` and `save` deliberately do nothing. ForgetfulHistory set the
    precedent for a History that declines to write.
    """

    def __init__(self, session: Session):
        self.session = session
        names = names_by_id(session)
        self.seen = _pair_keys(session, names)
        self.recent = _pair_keys(session, names, _recent_round_ids(session))
        self.data = {"rounds": [], "pairs_seen": sorted(self.seen)}

    def record(self, groups, unmatched, when: str) -> None:
        return None

    def save(self, path: str = pair.HISTORY_FILE) -> str:
        return "History lives in Postgres; the saved round is the record."


# --------------------------------------------------------------- persisting --


def save_round(session: Session, result: pair.RoundResult, config: pair.RoundConfig,
               when: date, headcount: int, source: str = "cli") -> models.Round:
    """Write a finished round: the groups, who was in them, and who was left out."""
    ids = ids_by_name(session)
    missing = [
        person.name
        for group in list(result.groups) + [tuple(result.unmatched)]
        for person in group
        if person.name not in ids
    ]
    if missing:
        raise LookupError("not on the roster: " + ", ".join(sorted(missing)))

    round_row = models.Round(
        ran_on=when,
        require_overlap=config.require_overlap,
        seed=config.seed,
        total_score=result.total,
        headcount=headcount,
        source=source,
    )
    session.add(round_row)

    for position, (members, report) in enumerate(zip(result.groups, result.reports), 1):
        score = report.score
        round_row.groups.append(models.RoundGroup(
            position=position,
            shared_slots=list(report.slots),
            shared_topics=list(report.topics),
            formats=list(report.formats),
            score=score.value if score else None,
            score_reasons=list(score.reasons) if score else [],
            members=[models.GroupMember(participant_id=ids[m.name]) for m in members],
        ))

    round_row.unmatched = [
        models.RoundUnmatched(participant_id=ids[person.name]) for person in result.unmatched
    ]
    session.commit()
    return round_row
