"""Running a round against the database, and reading rounds back out.

The round itself is still `pair.CoffeeRound`. This module only supplies it with
people and a History, then stores what came back.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

import pair
from app import adapters, models

MINIMUM_PARTICIPANTS = 2


class NotEnoughParticipants(Exception):
    """Fewer than two active people on the roster."""


@dataclass
class RoundOutcome:
    result: pair.RoundResult
    lines: List[str]
    headcount: int
    round_id: Optional[int]  # None for a preview, which is not stored


def run_round(session: Session, config: pair.RoundConfig, when: Optional[date] = None,
              source: str = "cli", store: Optional[bool] = None) -> RoundOutcome:
    """Score, match and (unless previewing) store one round.

    `config.keep_history` decides whether past rounds are *consulted*, matching
    what `--no-history` means in pair.py. `store` decides whether this round is
    written, so a preview can still avoid re-pairing people who just met.
    """
    keep = config.keep_history
    should_store = keep if store is None else (store and keep)

    people = adapters.active_participants(session)
    if len(people) < MINIMUM_PARTICIPANTS:
        raise NotEnoughParticipants(
            "Need at least " + str(MINIMUM_PARTICIPANTS) + " active participants; found "
            + str(len(people)) + "."
        )

    random.seed(config.seed)
    history = adapters.DatabaseHistory(session) if keep else pair.ForgetfulHistory()
    result = pair.CoffeeRound(people, history, config).run()
    lines = pair.render(result, config, len(people))

    round_id = None
    if should_store:
        stored = adapters.save_round(
            session, result, config, when or date.today(), len(people), source
        )
        round_id = stored.id

    return RoundOutcome(result=result, lines=lines, headcount=len(people), round_id=round_id)


# ------------------------------------------------------------------ reading --


def _with_details(query):
    return query.options(
        selectinload(models.Round.groups)
        .selectinload(models.RoundGroup.members)
        .selectinload(models.GroupMember.participant),
        selectinload(models.Round.unmatched).selectinload(models.RoundUnmatched.participant),
    )


def latest_round(session: Session) -> Optional[models.Round]:
    return session.scalars(
        _with_details(select(models.Round))
        .order_by(models.Round.ran_on.desc(), models.Round.id.desc())
        .limit(1)
    ).first()


def round_by_id(session: Session, round_id: int) -> Optional[models.Round]:
    return session.scalars(
        _with_details(select(models.Round)).where(models.Round.id == round_id)
    ).first()


def recent_rounds(session: Session, limit: int = 20) -> List[models.Round]:
    return list(
        session.scalars(
            select(models.Round)
            .order_by(models.Round.ran_on.desc(), models.Round.id.desc())
            .limit(limit)
        ).all()
    )


def group_counts(session: Session, round_ids: List[int]):
    """Group and unmatched counts per round, for the round list."""
    if not round_ids:
        return {}
    groups = dict(
        session.execute(
            select(models.RoundGroup.round_id, func.count())
            .where(models.RoundGroup.round_id.in_(round_ids))
            .group_by(models.RoundGroup.round_id)
        ).all()
    )
    unmatched = dict(
        session.execute(
            select(models.RoundUnmatched.round_id, func.count())
            .where(models.RoundUnmatched.round_id.in_(round_ids))
            .group_by(models.RoundUnmatched.round_id)
        ).all()
    )
    return {rid: (groups.get(rid, 0), unmatched.get(rid, 0)) for rid in round_ids}
