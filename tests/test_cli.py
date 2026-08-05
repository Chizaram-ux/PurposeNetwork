"""The commands the GitHub Action and a maintainer use."""

from __future__ import annotations

import json

from app import adapters, cli, db, models


REPO_HISTORY = {
    "rounds": [
        {
            "date": "2026-08-03",
            "pairs": [
                "Chizaram Agbanelo | Maya Hollander",
                "Isabella Tang | Maya Hollander",
                "Chizaram Agbanelo | Isabella Tang",
            ],
            "unmatched": [],
        }
    ],
    "pairs_seen": [
        "Chizaram Agbanelo | Isabella Tang",
        "Chizaram Agbanelo | Maya Hollander",
        "Isabella Tang | Maya Hollander",
    ],
}

REPO_CSV = """name,entity,team,format,availability,topics,email
Maya Hollander,Purpose Unlimited,People & Culture,Online,Mon PM;Wed PM;Fri PM,Career journey;Advice,maya@example.com
Chizaram Agbanelo,Purpose Unlimited,Engineering,Online,Wed PM,Sports;Finance;Tech,
Isabella Tang,Purpose Investments,Fund Operations,Online,Tue AM;Wed AM,Future outlooks,isabella@example.com
"""


def write_legacy(tmp_path, history=REPO_HISTORY):
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(REPO_CSV, encoding="utf-8")
    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps(history), encoding="utf-8")
    return str(csv_path), str(history_path)


def import_legacy(database, tmp_path, extra=()):
    csv_path, history_path = write_legacy(tmp_path)
    return cli.main([
        "--database-url", database, "import-legacy",
        "--participants", csv_path, "--history", history_path, *extra,
    ])


def test_the_csv_roster_is_imported_with_normalised_slots(database, tmp_path, capsys):
    assert import_legacy(database, tmp_path) == 0

    with db.session_scope() as session:
        people = adapters.active_participants(session)
        assert [person.name for person in people] == [
            "Chizaram Agbanelo", "Isabella Tang", "Maya Hollander",
        ]
        maya = [p for p in people if p.name == "Maya Hollander"][0]
        assert maya.slots == frozenset({"Mon PM", "Wed PM", "Fri PM"})
        assert maya.entity == "Purpose Unlimited"
        # The email column comes across, and a blank one stays blank.
        assert maya.email == "maya@example.com"
        assert [p.email for p in people if p.name == "Chizaram Agbanelo"] == [""]

    assert "Participants added: 3" in capsys.readouterr().out


def test_a_triangle_of_pair_keys_becomes_one_group_of_three(database, tmp_path):
    import_legacy(database, tmp_path)

    with db.session_scope() as session:
        round_row = session.query(models.Round).one()
        assert round_row.source == "import"
        assert len(round_row.groups) == 1
        assert len(round_row.groups[0].members) == 3
        assert round_row.headcount == 3

        history = adapters.DatabaseHistory(session)
        assert history.seen == set(REPO_HISTORY["pairs_seen"])


def test_two_separate_pairs_stay_two_groups(database, tmp_path):
    csv_path, history_path = write_legacy(tmp_path)
    (tmp_path / "history.json").write_text(json.dumps({
        "rounds": [{
            "date": "2026-07-27",
            "pairs": ["Maya Hollander | Isabella Tang"],
            "unmatched": ["Chizaram Agbanelo"],
        }],
        "pairs_seen": ["Isabella Tang | Maya Hollander"],
    }), encoding="utf-8")

    cli.main(["--database-url", database, "import-legacy",
              "--participants", csv_path, "--history", history_path])

    with db.session_scope() as session:
        round_row = session.query(models.Round).one()
        assert [len(group.members) for group in round_row.groups] == [2]
        assert [e.participant.name for e in round_row.unmatched] == ["Chizaram Agbanelo"]
        assert round_row.headcount == 3


def test_importing_twice_is_refused_unless_forced(database, tmp_path, capsys):
    import_legacy(database, tmp_path)
    capsys.readouterr()

    assert import_legacy(database, tmp_path) == 1
    assert "--force" in capsys.readouterr().out

    assert import_legacy(database, tmp_path, extra=["--force"]) == 0
    with db.session_scope() as session:
        assert session.query(models.Round).count() == 2
        # The roster is not duplicated, only the history is re-read.
        assert session.query(models.Participant).count() == 3


def test_someone_only_in_the_history_is_kept_as_inactive(database, tmp_path):
    csv_path, history_path = write_legacy(tmp_path)
    (tmp_path / "history.json").write_text(json.dumps({
        "rounds": [{"date": "2026-07-20", "pairs": ["Maya Hollander | Former Colleague"],
                    "unmatched": []}],
        "pairs_seen": ["Former Colleague | Maya Hollander"],
    }), encoding="utf-8")

    cli.main(["--database-url", database, "import-legacy",
              "--participants", csv_path, "--history", history_path])

    with db.session_scope() as session:
        leaver = session.query(models.Participant).filter_by(name="Former Colleague").one()
        assert leaver.active is False
        assert "Former Colleague" not in [
            person.name for person in adapters.active_participants(session)
        ]
        assert adapters.DatabaseHistory(session).has_met("Former Colleague | Maya Hollander")


def test_run_round_prints_and_stores(database, tmp_path, capsys):
    import_legacy(database, tmp_path)
    capsys.readouterr()

    assert cli.main(["--database-url", database, "run-round",
                     "--seed", "11", "--explain", "--source", "github-action"]) == 0

    output = capsys.readouterr().out
    assert "Coffee Roulette pairings for" in output
    assert "3 participants" in output
    assert "Stored as round" in output

    with db.session_scope() as session:
        newest = session.query(models.Round).order_by(models.Round.id.desc()).first()
        assert newest.source == "github-action"
        assert newest.seed == 11


def test_run_round_dry_run_stores_nothing(database, tmp_path, capsys):
    import_legacy(database, tmp_path)
    with db.session_scope() as session:
        before = session.query(models.Round).count()
    capsys.readouterr()

    assert cli.main(["--database-url", database, "run-round", "--dry-run"]) == 0

    assert "Preview only" in capsys.readouterr().out
    with db.session_scope() as session:
        assert session.query(models.Round).count() == before


def test_run_round_needs_a_roster(database, capsys):
    cli.main(["--database-url", database, "init-db"])
    capsys.readouterr()

    assert cli.main(["--database-url", database, "run-round"]) == 1
    assert "at least 2 active participants" in capsys.readouterr().out


def test_show_round_prints_the_stored_round(database, tmp_path, capsys):
    import_legacy(database, tmp_path)
    cli.main(["--database-url", database, "run-round", "--seed", "2"])
    capsys.readouterr()

    assert cli.main(["--database-url", database, "show-round"]) == 0

    output = capsys.readouterr().out
    assert "Coffee Roulette pairings for" in output
    assert "Maya Hollander" in output


def test_init_db_hides_any_password(database, capsys):
    assert cli.main(["--database-url", database, "init-db"]) == 0
    assert "Tables are ready" in capsys.readouterr().out
