"""The email column, end to end, and the promise that it never leaves the server.

The invitation payload itself is pair.py's; what is tested here is that the
database path feeds it the same way the CSV path does, and that no HTTP response
carries an address.
"""

from __future__ import annotations

import json

import pair
from app import adapters, cli, db, rounds
from tests.conftest import add_participant, four_people

SIGNUP = {
    "name": "Isabella Tang",
    "entity": "Purpose Investments",
    "team": "Fund Operations",
    "email": "isabella.tang@purpose.ca",
    "availability": ["Tue AM"],
}


def test_an_address_reaches_the_engine(session):
    add_participant(session, "Maya", "Purpose Unlimited", "P&C", ["Mon AM"],
                    email="maya@example.com")

    person = adapters.active_participants(session)[0]

    assert person.email == "maya@example.com"


def test_the_payload_is_built_from_the_database(session, tmp_path):
    four_people(session)
    target = tmp_path / "mail.json"

    outcome = rounds.run_round(session, pair.RoundConfig(seed=4))
    pair.write_invitations(outcome.result, str(target))

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["groups"] == 2
    everyone = [address for invite in payload["invitations"] for address in invite["to"]]
    assert sorted(everyone) == ["ann@example.com", "ben@example.com", "cara@example.com"]
    # Dev has no address, so they are reported rather than silently dropped.
    assert payload["needsEmailAddress"] == ["Dev"]
    assert all(invite["subject"].startswith("Coffee Roulette: ") for invite in payload["invitations"])


def test_run_round_writes_the_payload(database, tmp_path, capsys):
    with db.session_scope() as session:
        four_people(session)
    target = tmp_path / "pairings.json"
    capsys.readouterr()

    assert cli.main(["--database-url", database, "run-round",
                     "--seed", "4", "--emails", str(target)]) == 0

    assert "Wrote 2 invitations to" in capsys.readouterr().out
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["needsEmailAddress"] == ["Dev"]


def test_signing_up_stores_the_address(client, session):
    client.post("/api/participants", json=SIGNUP)

    assert adapters.active_participants(session)[0].email == "isabella.tang@purpose.ca"


def test_an_address_is_optional(client):
    response = client.post("/api/participants", json=dict(SIGNUP, email=""))

    assert response.status_code == 201
    assert response.json()["has_email"] is False


def test_an_implausible_address_is_refused(client):
    response = client.post("/api/participants", json=dict(SIGNUP, email="not-an-address"))

    assert response.status_code == 422


def test_the_roster_reports_only_whether_an_address_exists(client):
    client.post("/api/participants", json=SIGNUP)

    response = client.get("/api/participants")

    assert response.json()[0]["has_email"] is True
    assert "isabella.tang@purpose.ca" not in response.text
    assert "email" not in [key for key in response.json()[0] if key != "has_email"]


def test_no_round_endpoint_leaks_an_address(client, session):
    four_people(session)
    outcome = rounds.run_round(session, pair.RoundConfig(seed=4))

    for path in ["/api/rounds/current", "/api/rounds/" + str(outcome.round_id),
                 "/api/rounds", "/api/stats", "/api/participants"]:
        body = client.get(path).text
        assert "@example.com" not in body, path


def test_the_page_asks_for_an_address(client):
    assert 'id="email"' in client.get("/").text
