"""Running rounds against the database."""

from __future__ import annotations

from datetime import date

import pytest

import pair
from app import models, rounds
from tests.conftest import add_participant, four_people


def names_in(round_row):
    return sorted(
        tuple(sorted(member.participant.name for member in group.members))
        for group in round_row.groups
    )


def test_a_round_is_stored_with_its_groups_and_score(session):
    four_people(session)

    outcome = rounds.run_round(session, pair.RoundConfig(seed=1), when=date(2026, 2, 2))

    stored = rounds.round_by_id(session, outcome.round_id)
    assert stored.ran_on == date(2026, 2, 2)
    assert stored.headcount == 4
    assert len(stored.groups) == 2
    assert all(len(group.members) == 2 for group in stored.groups)
    assert all(group.shared_slots == ["Mon AM", "Tue AM"] for group in stored.groups)
    assert all(group.score is not None and group.score_reasons for group in stored.groups)


def test_the_next_round_avoids_the_pairs_that_just_met(session):
    four_people(session)

    first = rounds.run_round(session, pair.RoundConfig(seed=7))
    second = rounds.run_round(session, pair.RoundConfig(seed=7))

    before = names_in(rounds.round_by_id(session, first.round_id))
    after = names_in(rounds.round_by_id(session, second.round_id))
    assert before != after, "a fresh pairing beats repeating one from last round"


def test_an_odd_person_joins_a_group_of_three(session):
    four_people(session)
    add_participant(session, "Eve", "Driven", "Legal", ["Mon AM", "Tue AM"])

    outcome = rounds.run_round(session, pair.RoundConfig(seed=3))

    stored = rounds.round_by_id(session, outcome.round_id)
    sizes = sorted(len(group.members) for group in stored.groups)
    assert sizes == [2, 3]
    assert not stored.unmatched


def test_require_overlap_leaves_the_unschedulable_person_out(session):
    four_people(session)
    add_participant(session, "Zed", "Driven", "Legal", ["Fri PM"])

    outcome = rounds.run_round(session, pair.RoundConfig(require_overlap=True, seed=5))

    stored = rounds.round_by_id(session, outcome.round_id)
    assert [entry.participant.name for entry in stored.unmatched] == ["Zed"]
    assert stored.require_overlap is True


def test_a_dry_run_stores_nothing_but_still_reads_history(session):
    four_people(session)
    stored = rounds.run_round(session, pair.RoundConfig(seed=7))

    preview = rounds.run_round(session, pair.RoundConfig(seed=7), store=False)

    assert preview.round_id is None
    assert session.query(models.Round).count() == 1
    # History was consulted, so the preview differs from the round just stored.
    assert names_in(rounds.round_by_id(session, stored.round_id)) != sorted(
        tuple(sorted(person.name for person in group)) for group in preview.result.groups
    )


def test_a_round_needs_two_people(session):
    add_participant(session, "Solo", "Driven", "Sales", ["Mon AM"])

    with pytest.raises(rounds.NotEnoughParticipants):
        rounds.run_round(session, pair.RoundConfig())


def test_latest_round_is_the_most_recent_one(session):
    four_people(session)
    rounds.run_round(session, pair.RoundConfig(seed=1), when=date(2026, 1, 5))
    newest = rounds.run_round(session, pair.RoundConfig(seed=2), when=date(2026, 3, 9))

    assert rounds.latest_round(session).id == newest.round_id
