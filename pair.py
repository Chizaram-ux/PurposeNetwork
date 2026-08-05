"""
Virtual Coffee Roulette - smarter pairing script.

Reads participants from participants.csv and builds coffee-chat groups using a
weighted score instead of a plain shuffle, so matches are more interesting and
actually schedulable:

  * overlapping availability is rewarded (or required with --require-overlap)
  * cross-entity pairs beat cross-team pairs, which beat same-team pairs
  * matching chat format (in-person / online) is rewarded
  * shared topics give the pair a ready-made conversation starter
  * pairs already in history.json are penalised, recent repeats most of all

For small rounds every possible set of pairings is evaluated and the highest
scoring combination wins; larger rounds fall back to a greedy pass. An odd
person is folded into the group that fits them best.

Usage:
    python pair.py                     # smart pairing, avoids past pairs
    python pair.py --require-overlap   # only pair people who share a time slot
    python pair.py --seed 42           # reproducible tie-breaking
    python pair.py --explain           # show the score behind each match
    python pair.py --no-history        # ignore and do not update history.json
"""

import argparse
import csv
import json
import os
import random
from datetime import date
from itertools import combinations

CSV_FILE = "participants.csv"
HISTORY_FILE = "history.json"

# --- scoring weights -------------------------------------------------------
W_NEW_PAIR = 8           # never been paired before
W_RECENT_REPEAT = -4     # paired within the last RECENT_ROUNDS rounds
W_DIFFERENT_ENTITY = 5   # Purpose Unlimited <-> Purpose Investments, etc.
W_DIFFERENT_TEAM = 3     # same entity, different team
W_SHARED_SLOT = 4        # they can actually find a time
W_SAME_FORMAT = 2        # both want in-person, or both want online
W_SHARED_TOPIC = 2       # per topic in common
MAX_TOPIC_BONUS = 4
UNMATCHED_PENALTY = -12  # leaving someone out is worse than an odd match
RECENT_ROUNDS = 3        # how many past rounds count as "recent"
EXACT_LIMIT = 14         # above this many people, use the greedy matcher

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
BLOCKS = ["AM", "PM"]
ALL_SLOTS = [day + " " + block for day in DAYS for block in BLOCKS]
SLOT_ORDER = {slot: i for i, slot in enumerate(ALL_SLOTS)}

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


def split_multi(value):
    """Split a form answer on ; or , into clean chunks."""
    chunks = []
    for part in (value or "").replace(",", ";").split(";"):
        part = part.strip()
        if part:
            chunks.append(part)
    return chunks


def normalise_slot(raw):
    """Turn 'Monday morning' or 'Mon PM' or 'I am flexible' into slot codes."""
    text = raw.strip().lower()
    if not text:
        return []
    if "flex" in text or "any time" in text or "anytime" in text:
        return list(ALL_SLOTS)
    day = None
    block = None
    for token in text.replace("/", " ").replace("-", " ").split():
        token = token.strip(".,'")
        if token in DAY_ALIASES:
            day = DAY_ALIASES[token]
        elif token in BLOCK_ALIASES:
            block = BLOCK_ALIASES[token]
    if day and block:
        return [day + " " + block]
    if day:
        return [day + " AM", day + " PM"]
    return [raw.strip()]


def sort_slots(slots):
    return sorted(slots, key=lambda s: (SLOT_ORDER.get(s, 99), s))


def load_participants(path=CSV_FILE):
    people = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            person = {}
            for key, value in row.items():
                if key:
                    person[key.strip()] = (value or "").strip()
            slots = []
            for chunk in split_multi(person.get("availability", "")):
                for slot in normalise_slot(chunk):
                    if slot not in slots:
                        slots.append(slot)
            person["availability"] = sort_slots(slots)
            person["flexible"] = len(slots) == len(ALL_SLOTS)
            person["topics"] = split_multi(person.get("topics", ""))
            person.setdefault("name", "Unnamed")
            person.setdefault("entity", "")
            person.setdefault("team", "")
            person.setdefault("format", "")
            people.append(person)
    return people


def load_history(path=HISTORY_FILE):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"rounds": [], "pairs_seen": []}


def save_history(history, path=HISTORY_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def pair_key(a, b):
    return " | ".join(sorted([a["name"], b["name"]]))


def recent_pairs(history, rounds=RECENT_ROUNDS):
    keys = set()
    for entry in history.get("rounds", [])[-rounds:]:
        for key in entry.get("pairs", []):
            keys.add(key)
    return keys


def shared_slots(a, b):
    return sort_slots(set(a["availability"]) & set(b["availability"]))


def shared_topics(a, b):
    lookup = {t.lower(): t for t in a["topics"]}
    return [lookup[t.lower()] for t in b["topics"] if t.lower() in lookup]


def score_pair(a, b, seen, recent):
    """Score how interesting (and workable) a pairing would be."""
    slots = shared_slots(a, b)
    topics = shared_topics(a, b)
    key = pair_key(a, b)
    score = 0
    reasons = []

    if a["entity"] and a["entity"] != b["entity"]:
        score += W_DIFFERENT_ENTITY
        reasons.append("different entity")
    elif a["team"] != b["team"]:
        score += W_DIFFERENT_TEAM
        reasons.append("different team")
    else:
        reasons.append("same team")

    if slots:
        score += W_SHARED_SLOT
        reasons.append(str(len(slots)) + " shared slot(s)")
    else:
        reasons.append("no shared slot")

    if a["format"] and a["format"].lower() == b["format"].lower():
        score += W_SAME_FORMAT
        reasons.append("both prefer " + a["format"].lower())

    if topics:
        score += min(len(topics) * W_SHARED_TOPIC, MAX_TOPIC_BONUS)
        reasons.append(str(len(topics)) + " shared topic(s)")

    if key not in seen:
        score += W_NEW_PAIR
        reasons.append("never met")
    elif key in recent:
        score += W_RECENT_REPEAT
        reasons.append("met in a recent round")
    else:
        reasons.append("met a while ago")

    return score, {"slots": slots, "topics": topics, "reasons": reasons}


def build_scores(people, seen, recent, require_overlap, jitter=0.75):
    """Score every possible pair once; jitter keeps ties from being stale."""
    table = {}
    for i, j in combinations(range(len(people)), 2):
        score, info = score_pair(people[i], people[j], seen, recent)
        if require_overlap and not info["slots"]:
            continue
        table[(i, j)] = (score + random.random() * jitter, info)
    return table


def exact_matching(indices, table):
    """Best possible set of pairings by total score (small rounds only)."""
    memo = {}

    def search(items):
        if not items:
            return 0.0, [], []
        if items in memo:
            return memo[items]
        first = items[0]
        best = None
        for pos in range(1, len(items)):
            other = items[pos]
            entry = table.get((first, other))
            if entry is None:
                continue
            rest = items[1:pos] + items[pos + 1:]
            sub_score, sub_pairs, sub_unmatched = search(rest)
            total = entry[0] + sub_score
            if best is None or total > best[0]:
                best = (total, [(first, other)] + sub_pairs, sub_unmatched)
        sub_score, sub_pairs, sub_unmatched = search(items[1:])
        total = sub_score + UNMATCHED_PENALTY
        if best is None or total > best[0]:
            best = (total, sub_pairs, [first] + sub_unmatched)
        memo[items] = best
        return best

    return search(tuple(indices))


def greedy_matching(indices, table):
    """Take the best available pair repeatedly (used for large rounds)."""
    available = set(indices)
    ranked = sorted(table.items(), key=lambda item: item[1][0], reverse=True)
    total = 0.0
    pairs = []
    for (i, j), entry in ranked:
        if i in available and j in available:
            available.discard(i)
            available.discard(j)
            pairs.append((i, j))
            total += entry[0]
    return total, pairs, sorted(available)


def fold_leftover(pairs, unmatched, table):
    """Turn a single leftover person into a group of three."""
    if len(unmatched) != 1 or not pairs:
        return pairs, unmatched
    solo = unmatched[0]
    best_index = None
    best_score = None
    for index, group in enumerate(pairs):
        i, j = group
        first = table.get((min(solo, i), max(solo, i)))
        second = table.get((min(solo, j), max(solo, j)))
        if first is None or second is None:
            continue
        total = first[0] + second[0]
        if best_score is None or total > best_score:
            best_index = index
            best_score = total
    if best_index is None:
        return pairs, unmatched
    i, j = pairs[best_index]
    pairs[best_index] = (i, j, solo)
    return pairs, []


def group_details(group, people):
    """Shared slots, shared topics and format agreement for a whole group."""
    members = [people[i] for i in group]
    slots = set(members[0]["availability"])
    topics = {t.lower(): t for t in members[0]["topics"]}
    for member in members[1:]:
        slots &= set(member["availability"])
        theirs = {t.lower() for t in member["topics"]}
        topics = {k: v for k, v in topics.items() if k in theirs}
    formats = {m["format"].lower() for m in members if m["format"]}
    return sort_slots(slots), list(topics.values()), formats


def describe(index, group, people, table, explain=False):
    members = [people[i] for i in group]
    slots, topics, formats = group_details(group, people)
    lines = [str(index) + ". " + " + ".join(m["name"] for m in members)]

    for m in members:
        where = " / ".join(x for x in [m["entity"], m["team"]] if x)
        free = ", ".join(m["availability"][:4]) if m["availability"] else "no slots given"
        if m["flexible"]:
            free = "flexible"
        lines.append("     " + m["name"] + " - " + (where or "team unknown") + " - free: " + free)

    if slots:
        when = ", ".join(slots[:3])
        if len(slots) > 3:
            when += " (+" + str(len(slots) - 3) + " more)"
    else:
        when = "no shared slot - agree a time by email"
    lines.append("     When:    " + when)

    if len(formats) == 1:
        lines.append("     Format:  " + sorted(formats)[0] + " (both agree)")
    elif formats:
        lines.append("     Format:  mixed (" + ", ".join(sorted(formats)) + ") - default to online")

    if topics:
        lines.append("     Topics:  " + ", ".join(topics))
    else:
        picks = [m["topics"][0] for m in members if m["topics"]]
        if picks:
            lines.append("     Topics:  no overlap - try " + " or ".join(chr(34) + p + chr(34) for p in picks))

    if explain and len(group) == 2:
        entry = table.get((min(group), max(group)))
        if entry:
            lines.append("     Score:   " + str(round(entry[0], 1)) + " (" + ", ".join(entry[1]["reasons"]) + ")")

    return lines


def main():
    parser = argparse.ArgumentParser(description="Virtual Coffee Roulette pairing")
    parser.add_argument("--require-overlap", action="store_true",
                        help="only pair people who share an availability slot")
    parser.add_argument("--seed", type=int, default=None,
                        help="random seed for reproducible tie-breaking")
    parser.add_argument("--explain", action="store_true",
                        help="show the score and reasons behind each match")
    parser.add_argument("--no-history", action="store_true",
                        help="ignore and do not update history.json")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    people = load_participants()
    if len(people) < 2:
        print("Need at least two participants in " + CSV_FILE + ".")
        return

    history = {"rounds": [], "pairs_seen": []} if args.no_history else load_history()
    seen = set(history.get("pairs_seen", []))
    recent = recent_pairs(history)

    table = build_scores(people, seen, recent, args.require_overlap)
    indices = list(range(len(people)))
    if len(people) <= EXACT_LIMIT:
        total, pairs, unmatched = exact_matching(indices, table)
    else:
        total, pairs, unmatched = greedy_matching(indices, table)
    pairs, unmatched = fold_leftover(list(pairs), list(unmatched), table)

    print("Coffee Roulette pairings for " + date.today().isoformat())
    summary = str(len(people)) + " participants, " + str(len(pairs)) + " groups"
    if args.require_overlap:
        summary += ", overlapping availability required"
    print(summary)
    print("")

    for index, group in enumerate(pairs, 1):
        for line in describe(index, group, people, table, args.explain):
            print(line)
        print("")

    if unmatched:
        print("Unmatched this round: " + ", ".join(people[i]["name"] for i in unmatched))
        if args.require_overlap:
            print("Tip: no availability overlap - drop --require-overlap or ask them for more slots.")

    if args.explain:
        print("Total match score: " + str(round(total, 1)))

    if not args.no_history:
        round_pairs = []
        for group in pairs:
            for a, b in combinations(group, 2):
                key = pair_key(people[a], people[b])
                round_pairs.append(key)
                seen.add(key)
        history["rounds"].append({
            "date": date.today().isoformat(),
            "pairs": round_pairs,
            "unmatched": [people[i]["name"] for i in unmatched],
        })
        history["pairs_seen"] = sorted(seen)
        save_history(history)
        print("Saved round to " + HISTORY_FILE + ".")


if __name__ == "__main__":
    main()
