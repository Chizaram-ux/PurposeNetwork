"""The database adapters, especially the derived "who has already met"."""

from __future__ import annotations

import pair
from app import adapters
from tests.conftest import add_participant, four_people, store_round


def test_row_becomes_the_engines_participant(session):
    add_participant(session, "Maya", "Purpose Unlimited", "People & Culture",
                    ["Mon PM", "Wed PM"], topics=["Advice"])
    person = adapters.active_participants(session)[0]

    assert isinstance(person, pair.Participant)
    assert person.slots == frozenset({"Mon PM", "Wed PM"})
    assert person.where == "Purpose Unlimited / People & Culture"
    assert person.topics == ("Advice",)


def test_inactive_people_are_left_out_of_a_round(session):
    add_participant(session, "Maya", "Purpose Unlimited", "P&C", ["Mon AM"])
    retired = add_participant(session, "Sam", "Driven", "Sales", ["Mon AM"])
    retired.active = False
    session.commit()

    assert [person.name for person in adapters.active_participants(session)] == ["Maya"]


def test_a_group_of_three_counts_as_three_connections(session):
    four_people(session)
    store_round(session, [["Ann", "Ben", "Cara"]])

    history = adapters.DatabaseHistory(session)

    assert history.has_met("Ann | Ben")
    assert history.has_met("Ann | Cara")
    assert history.has_met("Ben | Cara")
    assert not history.has_met("Ann | Dev")


def test_only_the_last_three_rounds_count_as_recent(session):
    four_people(session)
    store_round(session, [["Ann", "Ben"]], when="2026-01-05")
    store_round(session, [["Ann", "Cara"]], when="2026-01-12")
    store_round(session, [["Ann", "Dev"]], when="2026-01-19")
    store_round(session, [["Ben", "Cara"]], when="2026-01-26")

    history = adapters.DatabaseHistory(session)

    assert history.has_met("Ann | Ben")          # still remembered
    assert not history.met_recently("Ann | Ben") # but four rounds ago
    assert history.met_recently("Ben | Cara")
    assert history.met_recently("Ann | Dev")


def test_history_never_writes_to_the_json_file(session, tmp_path):
    four_people(session)
    history = adapters.DatabaseHistory(session)
    target = tmp_path / "history.json"

    history.record([], [], "2026-01-05")
    message = history.save(str(target))

    assert not target.exists()
    assert "Postgres" in message


def test_pair_keys_match_the_engines_format(session):
    assert adapters.key_for_names("Zoe", "Adam") == "Adam | Zoe"
    a, b = pair.Participant(name="Zoe"), pair.Participant(name="Adam")
    assert adapters.key_for_names("Zoe", "Adam") == pair.pair_key(a, b)


def test_form_wording_still_normalises(session):
    assert adapters.normalise_slots("Monday morning; wednesday") == [
        "Mon AM", "Wed AM", "Wed PM",
    ]
    assert adapters.normalise_slots("I am flexible / any time works") == list(pair.ALL_SLOTS)
    assert adapters.normalise_slots(["Mon AM", "Fri PM"]) == ["Mon AM", "Fri PM"]
