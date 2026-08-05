"""Command line entry points for the database-backed app.

    python -m app.cli init-db          create the tables
    python -m app.cli import-legacy    load participants.csv and history.json
    python -m app.cli run-round        run a round and store it
    python -m app.cli show-round       print a stored round

run-round is what the scheduled GitHub Action calls, so the Action needs no
knowledge of the schema - only a DATABASE_URL. `run-round --emails FILE` writes
the same invitation payload as `pair.py --emails`, which is what the workflow
posts to the Power Automate mail flow.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import date
from typing import Dict, List, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

import pair
from app import adapters, db, models, rounds


# ------------------------------------------------------------------ init-db --


def init_db(args: argparse.Namespace) -> int:
    db.create_all()
    print("Tables are ready in " + _safe_url())
    return 0


def _safe_url() -> str:
    """The database URL with any password removed, safe to print in a log."""
    return db.engine().url.render_as_string(hide_password=True)


# ------------------------------------------------------------ import-legacy --


def import_legacy(args: argparse.Namespace) -> int:
    db.create_all()
    with db.session_scope() as session:
        added = _import_participants(session, args.participants)
        print("Participants added: " + str(added))

        if not os.path.exists(args.history):
            print("No " + args.history + " to import.")
            return 0

        existing = session.scalar(select(models.Round.id).limit(1))
        if existing and not args.force:
            print("Rounds already exist; re-run with --force to import history anyway.")
            return 1

        imported = _import_history(session, args.history)
        session.commit()
        print("Rounds imported: " + str(imported))
    return 0


def _import_participants(session: Session, path: str) -> int:
    """Load the CSV roster, keeping the raw availability wording alongside slots."""
    if not os.path.exists(path):
        print("No " + path + " to import.")
        return 0

    known = set(adapters.ids_by_name(session))
    added = 0
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            person = pair.participant_from_row(row)
            if person.name in known:
                continue
            session.add(models.Participant(
                name=person.name,
                entity=person.entity,
                team=person.team,
                chat_format=person.chat_format,
                email=person.email,
                availability_raw=(row.get("availability") or "").strip(),
                slots=list(pair.order_slots(person.slots)),
                topics=list(person.topics),
                active=True,
            ))
            known.add(person.name)
            added += 1
    session.commit()
    return added


def _import_history(session: Session, path: str) -> int:
    """Rebuild rounds from history.json.

    The file only stored `"A | B"` pair keys, so a group of three appears as its
    three pairs. Grouping by connected component recovers the original groups.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    known = set(adapters.ids_by_name(session))
    for name in sorted(_names_in(data) - known):
        # Someone who has taken part but is no longer on the roster: keep them,
        # inactive, so their past pairs still count as "already met".
        session.add(models.Participant(name=name, active=False))
    session.flush()
    ids = adapters.ids_by_name(session)

    imported = 0
    for entry in data.get("rounds", []):
        keys = entry.get("pairs", [])
        groups = _components([_split_key(key) for key in keys])
        round_row = models.Round(
            ran_on=date.fromisoformat(entry["date"]),
            require_overlap=False,
            headcount=len({name for group in groups for name in group})
            + len(entry.get("unmatched", [])),
            source="import",
        )
        for position, group in enumerate(groups, 1):
            round_row.groups.append(models.RoundGroup(
                position=position,
                members=[models.GroupMember(participant_id=ids[name]) for name in sorted(group)],
            ))
        round_row.unmatched = [
            models.RoundUnmatched(participant_id=ids[name])
            for name in entry.get("unmatched", [])
            if name in ids
        ]
        session.add(round_row)
        imported += 1
    return imported


def _split_key(key: str) -> Tuple[str, str]:
    left, _, right = key.partition(" | ")
    return left.strip(), right.strip()


def _names_in(data: dict) -> Set[str]:
    names: Set[str] = set()
    for key in data.get("pairs_seen", []):
        names.update(_split_key(key))
    for entry in data.get("rounds", []):
        for key in entry.get("pairs", []):
            names.update(_split_key(key))
        names.update(entry.get("unmatched", []))
    return {name for name in names if name}


def _components(pairs: Sequence[Tuple[str, str]]) -> List[List[str]]:
    """Connected components of the pair graph, each one a coffee group."""
    neighbours: Dict[str, Set[str]] = defaultdict(set)
    for left, right in pairs:
        neighbours[left].add(right)
        neighbours[right].add(left)

    seen: Set[str] = set()
    groups: List[List[str]] = []
    for start in sorted(neighbours):
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            node = stack.pop()
            group.append(node)
            for neighbour in sorted(neighbours[node]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        groups.append(sorted(group))
    return groups


# ---------------------------------------------------------------- run-round --


def run_round(args: argparse.Namespace) -> int:
    config = pair.RoundConfig(
        require_overlap=args.require_overlap,
        seed=args.seed,
        explain=args.explain,
        keep_history=not args.no_history,
        emails=args.emails,
    )
    with db.session_scope() as session:
        try:
            outcome = rounds.run_round(
                session, config, source=args.source, store=not args.dry_run
            )
        except rounds.NotEnoughParticipants as problem:
            print(str(problem))
            return 1

        for line in outcome.lines:
            print(line)

        # The same invitation payload pair.py writes, built from the same
        # reports, so the Power Automate flow does not care which path ran.
        if config.emails:
            print(pair.write_invitations(outcome.result, config.emails))

        print("")
        print(
            "Preview only; nothing was stored."
            if outcome.round_id is None
            else "Stored as round " + str(outcome.round_id) + "."
        )
    return 0


# --------------------------------------------------------------- show-round --


def show_round(args: argparse.Namespace) -> int:
    with db.session_scope() as session:
        row = (
            rounds.latest_round(session)
            if args.round_id is None
            else rounds.round_by_id(session, args.round_id)
        )
        if row is None:
            print("No such round.")
            return 1
        print("Coffee Roulette pairings for " + row.ran_on.isoformat())
        print(str(row.headcount) + " participants, " + str(len(row.groups)) + " groups")
        print("")
        for group in row.groups:
            names = " + ".join(member.participant.name for member in group.members)
            print(str(group.position) + ". " + names)
            for member in group.members:
                person = adapters.to_participant(member.participant)
                print("     " + person.name + " - " + person.where + " - free: " + person.free_text)
            print("     When:    " + (", ".join(group.shared_slots)
                                      or "no shared slot - agree a time by email"))
            print("     Topics:  " + (", ".join(group.shared_topics) or "no overlap"))
            if group.score is not None:
                print("     Score:   " + format(round(group.score, 1), "g")
                      + " (" + ", ".join(group.score_reasons) + ")")
            print("")
        if row.unmatched:
            print("Unmatched: " + ", ".join(sorted(e.participant.name for e in row.unmatched)))
    return 0


# --------------------------------------------------------------- the parser --


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coffee Roulette database commands")
    parser.add_argument("--database-url", default=None,
                       help="override DATABASE_URL for this command")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the tables").set_defaults(handler=init_db)

    legacy = sub.add_parser("import-legacy", help="load participants.csv and history.json")
    legacy.add_argument("--participants", default=pair.CSV_FILE)
    legacy.add_argument("--history", default=pair.HISTORY_FILE)
    legacy.add_argument("--force", action="store_true",
                        help="import history even though rounds already exist")
    legacy.set_defaults(handler=import_legacy)

    round_cmd = sub.add_parser("run-round", help="run a round and store it")
    round_cmd.add_argument("--require-overlap", action="store_true",
                           help="only pair people who share an availability slot")
    round_cmd.add_argument("--seed", type=int, default=None,
                           help="random seed for reproducible tie-breaking")
    round_cmd.add_argument("--explain", action="store_true",
                           help="show the score and reasons behind each match")
    round_cmd.add_argument("--dry-run", action="store_true",
                           help="preview the round without storing it")
    round_cmd.add_argument("--no-history", action="store_true",
                           help="ignore past rounds entirely (implies --dry-run)")
    round_cmd.add_argument("--emails", metavar="FILE", default=None,
                           help="write the per-group email payload as JSON")
    round_cmd.add_argument("--source", default="cli",
                           help="what triggered this round, recorded on the round")
    round_cmd.set_defaults(handler=run_round)

    show = sub.add_parser("show-round", help="print a stored round")
    show.add_argument("round_id", nargs="?", type=int, default=None)
    show.set_defaults(handler=show_round)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    db.configure(args.database_url)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
