"""Test fixtures.

The suite runs on SQLite so it needs no database server; the list columns are
declared with a SQLite variant in models.py precisely so this works. Anything
Postgres-specific would have to be covered by a deployment check instead.
"""

from __future__ import annotations

import os
import sys
from datetime import date

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import adapters, db, models


@pytest.fixture()
def database(tmp_path):
    """A throwaway database, wired into the app for the duration of one test."""
    url = "sqlite+pysqlite:///" + str(tmp_path / "roulette.sqlite3")
    db.configure(url)
    models.Base.metadata.create_all(db.engine())
    yield url
    db.engine().dispose()


@pytest.fixture()
def session(database):
    factory = db.session_factory()
    made = factory()
    try:
        yield made
    finally:
        made.close()


@pytest.fixture()
def client(database):
    from app.api import app

    with TestClient(app) as test_client:
        yield test_client


def add_participant(session, name, entity, team, slots, topics=(), chat_format="Online",
                    email=""):
    row = models.Participant(
        name=name,
        entity=entity,
        team=team,
        chat_format=chat_format,
        email=email,
        availability_raw="; ".join(slots),
        slots=list(slots),
        topics=list(topics),
        active=True,
    )
    session.add(row)
    session.commit()
    return row


def store_round(session, groups, when="2026-01-05", unmatched=()):
    """Store a round directly, for tests that need a history to read back."""
    ids = adapters.ids_by_name(session)
    round_row = models.Round(ran_on=date.fromisoformat(when), headcount=len(ids), source="test")
    for position, names in enumerate(groups, 1):
        round_row.groups.append(models.RoundGroup(
            position=position,
            members=[models.GroupMember(participant_id=ids[name]) for name in names],
        ))
    round_row.unmatched = [
        models.RoundUnmatched(participant_id=ids[name]) for name in unmatched
    ]
    session.add(round_row)
    session.commit()
    return round_row


def four_people(session):
    add_participant(session, "Ann", "Driven", "Sales", ["Mon AM", "Tue AM"],
                    email="ann@example.com")
    add_participant(session, "Ben", "Harness", "Support", ["Mon AM", "Tue AM"],
                    email="ben@example.com")
    add_participant(session, "Cara", "Purpose Investments", "Ops", ["Mon AM", "Tue AM"],
                    email="cara@example.com")
    # Dev has no address on purpose: they should surface under needsEmailAddress.
    add_participant(session, "Dev", "Purpose Unlimited", "Eng", ["Mon AM", "Tue AM"])
