"""Virtual Coffee Roulette - the pairing engine.

The round is assembled from small layers instead of one long function:

    model      Participant and Pairing value objects
    parsing    Microsoft Forms wording and CSV rows become Participants
    history    what already happened, and how recently
    scoring    a table of Rules turns a Pairing into a score plus reasons
    matching   strategies that turn scores into groups
    reporting  turns groups into the lines that get printed
    cli        wires the layers together

Adding a new preference means adding one Rule to RULES; the parser, the
matcher and the report stay untouched. Turning history off swaps in a
do-nothing History rather than sprinkling flag checks through the code.

Usage:
    python pair.py                     # smart pairing, avoids past pairs
    python pair.py --require-overlap   # only pair people who share a time slot
    python pair.py --seed 42           # reproducible tie-breaking
    python pair.py --explain           # show the score behind each match
    python pair.py --no-history        # do not read or update history.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------- settings --

CSV_FILE = "participants.csv"
HISTORY_FILE = "history.json"

RECENT_ROUNDS = 3          # how many past rounds still count as recent
EXHAUSTIVE_LIMIT = 14      # above this many people, use the greedy matcher
UNMATCHED_PENALTY = -12.0  # leaving someone out is worse than an odd match
TIE_BREAK_JITTER = 0.75    # nudge so equal-scoring rounds do not repeat

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
BLOCKS = ("AM", "PM")
ALL_SLOTS: Tuple[str, ...] = tuple(day + " " + block for day in DAYS for block in BLOCKS)
SLOT_ORDER: Dict[str, int] = {slot: index for index, slot in enumerate(ALL_SLOTS)}


def order_slots(slots: Iterable[str]) -> Tuple[str, ...]:
    """Chronological order, with anything unrecognised sorted to the end."""
    return tuple(sorted(set(slots), key=lambda slot: (SLOT_ORDER.get(slot, len(ALL_SLOTS)), slot)))


# ------------------------------------------------------------------ model --


@dataclass(frozen=True)
class Participant:
    name: str
    entity: str = ""
    team: str = ""
    chat_format: str = ""
    slots: frozenset = frozenset()
    topics: Tuple[str, ...] = ()

    @property
    def is_flexible(self) -> bool:
        return len(self.slots) == len(ALL_SLOTS)

    @property
    def where(self) -> str:
        return " / ".join(part for part in (self.entity, self.team) if part) or "team unknown"

    @property
    def free_text(self) -> str:
        listed = ", ".join(order_slots(self.slots)[:4]) or "no slots given"
        return {True: "flexible", False: listed}[self.is_flexible]


@dataclass(frozen=True)
class Pairing:
    """Two people plus everything the rules need in order to judge them."""

    a: Participant
    b: Participant
    shared_slots: Tuple[str, ...] = ()
    shared_topics: Tuple[str, ...] = ()
    met_before: bool = False
    met_recently: bool = False

    @property
    def different_entity(self) -> bool:
        return bool(self.a.entity) and self.a.entity != self.b.entity

    @property
    def same_entity_other_team(self) -> bool:
        return not self.different_entity and self.a.team != self.b.team

    @property
    def same_format(self) -> bool:
        return bool(self.a.chat_format) and self.a.chat_format.lower() == self.b.chat_format.lower()


def pair_key(a: Participant, b: Participant) -> str:
    return " | ".join(sorted([a.name, b.name]))


def shared_topics(a: Participant, b: Participant) -> Tuple[str, ...]:
    by_lower = {topic.lower(): topic for topic in a.topics}
    return tuple(by_lower[topic.lower()] for topic in b.topics if topic.lower() in by_lower)


# ---------------------------------------------------------------- parsing --


class FormAnswers:
    """Knows how Microsoft Forms writes availability and topic answers."""

    DAY_ALIASES = {
        "mon": "Mon", "monday": "Mon",
        "tue": "Tue", "tues": "Tue", "tuesday": "Tue",
        "wed": "Wed", "weds": "Wed", "wednesday": "Wed",
        "thu": "Thu", "thur": "Thu", "thurs": "Thu", "thursday": "Thu",
        "fri": "Fri", "friday": "Fri",
    }
    BLOCK_ALIASES = {
        "am": "AM", "morning": "AM", "mornings": "AM",
        "pm": "PM", "afternoon": "PM", "afternoons": "PM",
    }
    FLEXIBLE_MARKERS = ("flex", "any time", "anytime")

    @classmethod
    def values(cls, raw: str) -> Tuple[str, ...]:
        """Split a multi-select answer written with ; or , separators."""
        parts = (raw or "").replace(",", ";").split(";")
        return tuple(part.strip() for part in parts if part.strip())

    @classmethod
    def slots(cls, raw: str) -> Tuple[str, ...]:
        found: List[str] = []
        for value in cls.values(raw):
            found.extend(cls._slots_for(value))
        return order_slots(found)

    @classmethod
    def _slots_for(cls, value: str) -> Tuple[str, ...]:
        text = value.lower()
        if any(marker in text for marker in cls.FLEXIBLE_MARKERS):
            return ALL_SLOTS
        return cls._expand(*cls._day_and_block(text), fallback=value)

    @classmethod
    def _day_and_block(cls, text: str):
        day = None
        block = None
        for token in text.replace("/", " ").replace("-", " ").split():
            token = token.strip(".,")
            day = cls.DAY_ALIASES.get(token, day)
            block = cls.BLOCK_ALIASES.get(token, block)
        return day, block

    @staticmethod
    def _expand(day, block, fallback: str) -> Tuple[str, ...]:
        options = {
            (True, True): (str(day) + " " + str(block),),
            (True, False): (str(day) + " AM", str(day) + " PM"),
        }
        return options.get((bool(day), bool(block)), (fallback,))


def load_participants(path: str = CSV_FILE) -> List[Participant]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [participant_from_row(row) for row in csv.DictReader(handle)]


def participant_from_row(row: Dict[str, str]) -> Participant:
    def value(key: str) -> str:
        return (row.get(key) or "").strip()

    return Participant(
        name=value("name") or "Unnamed",
        entity=value("entity"),
        team=value("team"),
        chat_format=value("format"),
        slots=frozenset(FormAnswers.slots(value("availability"))),
        topics=FormAnswers.values(value("topics")),
    )


# ---------------------------------------------------------------- history --


class History:
    """Everything the rules need to know about previous rounds."""

    def __init__(self, data: Optional[dict] = None):
        self.data = data or {"rounds": [], "pairs_seen": []}
        self.seen = set(self.data.get("pairs_seen", []))
        self.recent = {
            key
            for entry in self.data.get("rounds", [])[-RECENT_ROUNDS:]
            for key in entry.get("pairs", [])
        }

    @classmethod
    def load(cls, path: str = HISTORY_FILE) -> "History":
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle))

    def has_met(self, key: str) -> bool:
        return key in self.seen

    def met_recently(self, key: str) -> bool:
        return key in self.recent

    def record(self, groups, unmatched, when: str) -> None:
        keys = [pair_key(a, b) for group in groups for a, b in combinations(group, 2)]
        self.seen.update(keys)
        self.data.setdefault("rounds", []).append({
            "date": when,
            "pairs": keys,
            "unmatched": [person.name for person in unmatched],
        })
        self.data["pairs_seen"] = sorted(self.seen)

    def save(self, path: str = HISTORY_FILE) -> str:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2)
        return "Saved round to " + path + "."


class ForgetfulHistory(History):
    """--no-history: knows nothing, records nothing, writes nothing."""

    def record(self, groups, unmatched, when: str) -> None:
        return None

    def save(self, path: str = HISTORY_FILE) -> str:
        return "History left untouched (--no-history)."


# ---------------------------------------------------------------- scoring --


@dataclass(frozen=True)
class Rule:
    """One reason to put two people together, or to keep them apart."""

    name: str
    weight: float
    applies: Callable[[Pairing], bool]
    times: Callable[[Pairing], int] = lambda pairing: 1
    cap: Optional[float] = None

    def points(self, pairing: Pairing) -> float:
        if not self.applies(pairing):
            return 0.0
        earned = self.weight * self.times(pairing)
        return min(earned, self.cap) if self.cap is not None else earned


RULES: Tuple[Rule, ...] = (
    Rule("never paired before", 8, lambda p: not p.met_before),
    Rule("met in a recent round", -4, lambda p: p.met_recently),
    Rule("different entity", 5, lambda p: p.different_entity),
    Rule("different team", 3, lambda p: p.same_entity_other_team),
    Rule("shared availability", 4, lambda p: bool(p.shared_slots)),
    Rule("same chat format", 2, lambda p: p.same_format),
    Rule("shared topics", 2, lambda p: bool(p.shared_topics),
         times=lambda p: len(p.shared_topics), cap=4),
)


@dataclass(frozen=True)
class Score:
    value: float
    reasons: Tuple[str, ...] = ()

    def __str__(self) -> str:
        return format(round(self.value, 1), "g") + " (" + ", ".join(self.reasons) + ")"


class PairScorer:
    def __init__(self, rules: Sequence[Rule] = RULES, jitter: float = 0.0, rng=None):
        self.rules = tuple(rules)
        self.jitter = jitter
        self.rng = rng or random

    def score(self, pairing: Pairing) -> Score:
        total = self.rng.random() * self.jitter
        reasons: List[str] = []
        for rule in self.rules:
            points = rule.points(pairing)
            total += points
            if points:
                reasons.append(rule.name)
        return Score(total, tuple(reasons))


class PairingBuilder:
    """Turns two Participants into a Pairing the rules can read."""

    def __init__(self, history: History):
        self.history = history

    def __call__(self, a: Participant, b: Participant) -> Pairing:
        key = pair_key(a, b)
        return Pairing(
            a=a,
            b=b,
            shared_slots=order_slots(a.slots & b.slots),
            shared_topics=shared_topics(a, b),
            met_before=self.history.has_met(key),
            met_recently=self.history.met_recently(key),
        )


def overlap_required(pairing: Pairing) -> bool:
    return bool(pairing.shared_slots)


class ScoreBoard:
    """Every allowed pair, scored exactly once."""

    def __init__(self, people: Sequence[Participant], scorer: PairScorer,
                 build_pairing: PairingBuilder, eligibility=()):
        self.people = list(people)
        self.scores: Dict[Tuple[int, int], Score] = {}
        for i, j in combinations(range(len(self.people)), 2):
            pairing = build_pairing(self.people[i], self.people[j])
            if all(check(pairing) for check in eligibility):
                self.scores[(i, j)] = scorer.score(pairing)

    def __len__(self) -> int:
        return len(self.people)

    @staticmethod
    def edge(i: int, j: int) -> Tuple[int, int]:
        return (min(i, j), max(i, j))

    def score_of(self, i: int, j: int) -> Optional[Score]:
        return self.scores.get(self.edge(i, j))

    def value_of(self, i: int, j: int) -> Optional[float]:
        score = self.score_of(i, j)
        return getattr(score, "value", None)

    def ranked(self):
        return sorted(self.scores.items(), key=lambda item: item[1].value, reverse=True)


# --------------------------------------------------------------- matching --


@dataclass
class MatchResult:
    groups: List[Tuple[int, ...]] = field(default_factory=list)
    unmatched: List[int] = field(default_factory=list)
    total: float = 0.0


def better(current: Optional[MatchResult], candidate: MatchResult) -> MatchResult:
    return candidate if current is None or candidate.total > current.total else current


class Matcher:
    def match(self, board: ScoreBoard) -> MatchResult:
        raise NotImplementedError


class ExhaustiveMatcher(Matcher):
    """Highest total score over every possible set of pairings."""

    def match(self, board: ScoreBoard) -> MatchResult:
        memo: Dict[Tuple[int, ...], MatchResult] = {}

        def search(items: Tuple[int, ...]) -> MatchResult:
            if not items:
                return MatchResult()
            if items in memo:
                return memo[items]
            first, rest = items[0], items[1:]
            best: Optional[MatchResult] = None
            for position, other in enumerate(rest):
                score = board.score_of(first, other)
                if score is None:
                    continue
                branch = search(rest[:position] + rest[position + 1:])
                best = better(best, MatchResult(
                    groups=[(first, other)] + branch.groups,
                    unmatched=list(branch.unmatched),
                    total=score.value + branch.total,
                ))
            branch = search(rest)
            best = better(best, MatchResult(
                groups=list(branch.groups),
                unmatched=[first] + list(branch.unmatched),
                total=branch.total + UNMATCHED_PENALTY,
            ))
            memo[items] = best
            return best

        return search(tuple(range(len(board))))


class GreedyMatcher(Matcher):
    """Repeatedly take the best still-available pair."""

    def match(self, board: ScoreBoard) -> MatchResult:
        available = set(range(len(board)))
        result = MatchResult()
        for (i, j), score in board.ranked():
            if {i, j} <= available:
                available -= {i, j}
                result.groups.append((i, j))
                result.total += score.value
        result.unmatched = sorted(available)
        result.total += UNMATCHED_PENALTY * len(result.unmatched)
        return result


def choose_matcher(count: int) -> Matcher:
    return ExhaustiveMatcher() if count <= EXHAUSTIVE_LIMIT else GreedyMatcher()


def fold_single_leftover(result: MatchResult, board: ScoreBoard) -> MatchResult:
    """A single spare person joins the pair that suits them best."""
    if len(result.unmatched) != 1 or not result.groups:
        return result
    solo = result.unmatched[0]
    options = []
    for index, group in enumerate(result.groups):
        values = [board.value_of(solo, member) for member in group]
        if None not in values:
            options.append((sum(values), index))
    if not options:
        return result
    index = max(options)[1]
    result.groups[index] = tuple(result.groups[index]) + (solo,)
    result.unmatched = []
    return result


# -------------------------------------------------------------- reporting --


def common_topics(members: Sequence[Participant]) -> Tuple[str, ...]:
    shared = {topic.lower(): topic for topic in members[0].topics}
    for member in members[1:]:
        theirs = {topic.lower() for topic in member.topics}
        shared = {key: value for key, value in shared.items() if key in theirs}
    return tuple(shared.values())


@dataclass(frozen=True)
class GroupReport:
    members: Tuple[Participant, ...]
    slots: Tuple[str, ...]
    topics: Tuple[str, ...]
    formats: Tuple[str, ...]
    score: Optional[Score] = None

    @classmethod
    def build(cls, members: Sequence[Participant], score: Optional[Score] = None) -> "GroupReport":
        slots = order_slots(set.intersection(*[set(member.slots) for member in members]))
        formats = tuple(sorted({m.chat_format.lower() for m in members if m.chat_format}))
        return cls(tuple(members), slots, common_topics(members), formats, score)

    def lines(self, index: int, explain: bool = False) -> List[str]:
        rows = [str(index) + ". " + " + ".join(member.name for member in self.members)]
        rows.extend("     " + m.name + " - " + m.where + " - free: " + m.free_text for m in self.members)
        details = (
            ("When", self.when_text()),
            ("Format", self.format_text()),
            ("Topics", self.topics_text()),
            ("Score", self.score_text(explain)),
        )
        rows.extend("     " + (label + ":").ljust(9) + text for label, text in details if text)
        return rows

    def when_text(self) -> str:
        extra = len(self.slots) - 3
        more = " (+" + str(extra) + " more)" if extra > 0 else ""
        return ", ".join(self.slots[:3]) + more or "no shared slot - agree a time by email"

    def format_text(self) -> str:
        wording = {0: "", 1: "(all agree)"}.get(len(self.formats), "- default to online")
        return (", ".join(self.formats) + " " + wording).strip()

    def topics_text(self) -> str:
        starters = " or ".join(chr(34) + m.topics[0] + chr(34) for m in self.members if m.topics)
        fallback = "no overlap - try " + starters if starters else ""
        return ", ".join(self.topics) or fallback

    def score_text(self, explain: bool) -> str:
        return str(self.score) if explain and self.score else ""


# ------------------------------------------------------------- the round ---


@dataclass(frozen=True)
class RoundConfig:
    require_overlap: bool = False
    seed: Optional[int] = None
    explain: bool = False
    keep_history: bool = True

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "RoundConfig":
        return cls(
            require_overlap=args.require_overlap,
            seed=args.seed,
            explain=args.explain,
            keep_history=not args.no_history,
        )

    @property
    def eligibility(self):
        return (overlap_required,) if self.require_overlap else ()


@dataclass
class RoundResult:
    reports: List[GroupReport]
    groups: List[Tuple[Participant, ...]]
    unmatched: List[Participant]
    total: float


class CoffeeRound:
    """Score, match, then report. One pass, three collaborators."""

    def __init__(self, people: Sequence[Participant], history: History, config: RoundConfig):
        self.people = list(people)
        self.history = history
        self.config = config

    def run(self) -> RoundResult:
        board = ScoreBoard(
            self.people,
            PairScorer(jitter=TIE_BREAK_JITTER),
            PairingBuilder(self.history),
            self.config.eligibility,
        )
        outcome = fold_single_leftover(choose_matcher(len(board)).match(board), board)
        groups = [tuple(self.people[i] for i in group) for group in outcome.groups]
        reports = [
            GroupReport.build(members, board.score_of(*indices) if len(indices) == 2 else None)
            for indices, members in zip(outcome.groups, groups)
        ]
        unmatched = [self.people[i] for i in outcome.unmatched]
        return RoundResult(reports, groups, unmatched, outcome.total)


def render(result: RoundResult, config: RoundConfig, headcount: int) -> List[str]:
    suffix = ", overlapping availability required" if config.require_overlap else ""
    lines = [
        "Coffee Roulette pairings for " + date.today().isoformat(),
        str(headcount) + " participants, " + str(len(result.reports)) + " groups" + suffix,
        "",
    ]
    for index, report in enumerate(result.reports, 1):
        lines.extend(report.lines(index, config.explain))
        lines.append("")
    lines.extend(unmatched_lines(result, config))
    lines.extend(["Total match score: " + format(round(result.total, 1), "g")] if config.explain else [])
    return lines


def unmatched_lines(result: RoundResult, config: RoundConfig) -> List[str]:
    if not result.unmatched:
        return []
    names = ", ".join(person.name for person in result.unmatched)
    tip = "Tip: no availability overlap - drop --require-overlap or ask them for more slots."
    return ["Unmatched this round: " + names] + ([tip] if config.require_overlap else [])


# ---------------------------------------------------------------- the cli --


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Virtual Coffee Roulette pairing")
    parser.add_argument("--require-overlap", action="store_true",
                        help="only pair people who share an availability slot")
    parser.add_argument("--seed", type=int, default=None,
                        help="random seed for reproducible tie-breaking")
    parser.add_argument("--explain", action="store_true",
                        help="show the score and reasons behind each match")
    parser.add_argument("--no-history", action="store_true",
                        help="ignore and do not update history.json")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    config = RoundConfig.from_args(parse_args(argv))
    random.seed(config.seed)

    people = load_participants()
    if len(people) < 2:
        print("Need at least two participants in " + CSV_FILE + ".")
        return 1

    history = History.load() if config.keep_history else ForgetfulHistory()
    result = CoffeeRound(people, history, config).run()
    for line in render(result, config, len(people)):
        print(line)

    history.record(result.groups, result.unmatched, date.today().isoformat())
    print(history.save())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
