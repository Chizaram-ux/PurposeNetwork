"""The HTTP surface: read-only pairings, plus sign-up."""

from __future__ import annotations

from datetime import date

import pair
from app import rounds
from tests.conftest import four_people

SIGNUP = {
    "name": "Isabella Tang",
    "entity": "Purpose Investments",
    "team": "Fund Operations",
    "chat_format": "Online",
    "availability": ["Tue AM", "Wed AM"],
    "topics": ["Future outlooks"],
}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_options_describe_the_form(client):
    options = client.get("/api/options").json()

    assert len(options["slots"]) == 10
    assert options["slots"][0] == "Mon AM"
    assert "Purpose Unlimited" in options["entities"]
    assert options["formats"] == ["Online", "In person"]


def test_options_state_the_timezone(client):
    """The slots are Toronto time, and the page has to say so."""
    options = client.get("/api/options").json()

    assert options["timezone_label"] == "Eastern time (ET)"
    assert options["timezone_short"] == "ET"


def test_the_page_shows_the_timezone_with_the_slots(client):
    page = client.get("/").text

    assert 'id="tz-note"' in page
    assert "state.timezoneShort" in page


def test_signing_up_normalises_availability(client):
    response = client.post("/api/participants", json=SIGNUP)

    assert response.status_code == 201
    person = response.json()
    assert person["slots"] == ["Tue AM", "Wed AM"]
    assert person["active"] is True
    assert client.get("/api/participants").json()[0]["name"] == "Isabella Tang"


def test_signing_up_accepts_raw_form_wording(client):
    payload = dict(SIGNUP, availability="Monday morning; wednesday")

    person = client.post("/api/participants", json=payload).json()

    assert person["slots"] == ["Mon AM", "Wed AM", "Wed PM"]


def test_flexible_wording_means_every_slot(client):
    payload = dict(SIGNUP, availability="I am flexible / any time works")

    person = client.post("/api/participants", json=payload).json()

    assert person["slots"] == list(pair.ALL_SLOTS)


def test_a_format_is_stored_with_its_usual_capitalisation(client):
    person = client.post("/api/participants", json=dict(SIGNUP, chat_format="ONLINE")).json()

    assert person["chat_format"] == "Online"


def test_signing_up_twice_is_refused(client):
    client.post("/api/participants", json=SIGNUP)

    response = client.post("/api/participants", json=SIGNUP)

    assert response.status_code == 409
    assert "already signed up" in response.json()["detail"]


def test_availability_is_required(client):
    response = client.post("/api/participants", json=dict(SIGNUP, availability=[]))

    assert response.status_code == 422
    assert "at least one time slot" in response.json()["detail"]


def test_a_name_is_required(client):
    response = client.post("/api/participants", json=dict(SIGNUP, name="   "))

    assert response.status_code == 422


def test_no_round_yet(client):
    response = client.get("/api/rounds/current")

    assert response.status_code == 404
    assert "No round has been run yet." in response.json()["detail"]


def test_the_current_round_is_readable(client, session):
    four_people(session)
    rounds.run_round(session, pair.RoundConfig(seed=4, explain=True))

    payload = client.get("/api/rounds/current").json()

    assert payload["headcount"] == 4
    assert payload["group_count"] == 2
    assert payload["unmatched"] == []
    group = payload["groups"][0]
    assert len(group["members"]) == 2
    assert group["shared_slots"] == ["Mon AM", "Tue AM"]
    assert group["score_reasons"]
    assert set(group["members"][0]) == {"name", "entity", "team", "chat_format", "slots"}


def test_rounds_are_listed_newest_first(client, session):
    four_people(session)
    rounds.run_round(session, pair.RoundConfig(seed=1), when=date(2026, 1, 5))
    rounds.run_round(session, pair.RoundConfig(seed=2), when=date(2026, 3, 9))

    listed = client.get("/api/rounds").json()

    assert [row["ran_on"] for row in listed] == ["2026-03-09", "2026-01-05"]
    assert listed[0]["group_count"] == 2


def test_one_round_by_id_and_a_missing_one(client, session):
    four_people(session)
    outcome = rounds.run_round(session, pair.RoundConfig(seed=1))

    assert client.get("/api/rounds/" + str(outcome.round_id)).status_code == 200
    assert client.get("/api/rounds/9999").status_code == 404


def test_rounds_cannot_be_created_over_http(client):
    """Pairings come from the scheduled job, so there is no POST for them."""
    assert client.post("/api/rounds", json={}).status_code == 405


def test_stats_count_people_rounds_and_connections(client, session):
    four_people(session)
    rounds.run_round(session, pair.RoundConfig(seed=1))

    stats = client.get("/api/stats").json()

    assert stats == {"participants": 4, "rounds": 1, "connections": 2}


def test_the_page_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Coffee Roulette" in response.text
