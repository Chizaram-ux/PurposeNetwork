"""
Virtual Coffee Roulette - random pairing script.

Reads participants from participants.csv, shuffles them, and creates
pairs for a coffee-chat round. Handles odd numbers by making one group
of three. Optionally avoids repeating pairs from previous rounds using
history.json, and can require an overlapping availability slot.

Usage:
    python pair.py                  # random pairing, avoids past pairs
    python pair.py --require-overlap # only pair people who share a time slot
    python pair.py --seed 42        # reproducible shuffle
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


def load_participants(path=CSV_FILE):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        people = []
        for row in reader:
            row["availability"] = [
                s.strip() for s in row.get("availability", "").split(";") if s.strip()
            ]
            row["topics"] = [
                s.strip() for s in row.get("topics", "").split(";") if s.strip()
            ]
            people.append(row)
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


def shares_slot(a, b):
    return bool(set(a["availability"]) & set(b["availability"]))


def make_pairs(people, seen_pairs, require_overlap=False):
    """Greedily build pairs, preferring people not paired before."""
    remaining = people[:]
    random.shuffle(remaining)
    pairs = []
    unmatched = []

    while len(remaining) > 1:
        person = remaining.pop()
        candidates = list(remaining)
        # Prefer partners not seen before (and sharing a slot if required).
        def score(c):
            not_repeat = pair_key(person, c) not in seen_pairs
            overlap_ok = shares_slot(person, c) if require_overlap else True
            return (overlap_ok, not_repeat)

        candidates.sort(key=score, reverse=True)
        partner = None
        for c in candidates:
            if not require_overlap or shares_slot(person, c):
                partner = c
                break
        if partner is None:
            unmatched.append(person)
            continue
        remaining.remove(partner)
        pairs.append((person, partner))

    if remaining:
        unmatched.extend(remaining)

    # Fold a single leftover into the last pair to form a group of three.
    if len(unmatched) == 1 and pairs:
        last = pairs.pop()
        pairs.append((last[0], last[1], unmatched.pop()))

    return pairs, unmatched


def format_group(group):
    names = " & ".join(p["name"] for p in group)
    shared = set(group[0]["availability"])
    for p in group[1:]:
        shared &= set(p["availability"])
    slot = ", ".join(sorted(shared)) if shared else "no shared slot - coordinate directly"
    return f"{names}  (suggested time: {slot})"


def main():
    parser = argparse.ArgumentParser(description="Virtual Coffee Roulette pairing")
    parser.add_argument("--require-overlap", action="store_true",
                        help="only pair people who share an availability slot")
    parser.add_argument("--seed", type=int, default=None,
                        help="random seed for reproducible pairings")
    parser.add_argument("--no-history", action="store_true",
                        help="ignore and do not update history.json")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    people = load_participants()
    history = {"rounds": [], "pairs_seen": []} if args.no_history else load_history()
    seen = set(history.get("pairs_seen", []))

    pairs, unmatched = make_pairs(people, seen, require_overlap=args.require_overlap)

    print(f"Coffee Roulette pairings for {date.today().isoformat()}\n")
    for i, group in enumerate(pairs, 1):
        print(f"{i}. {format_group(group)}")
    if unmatched:
        print("\nUnmatched this round: " + ", ".join(p["name"] for p in unmatched))

    if not args.no_history:
        round_pairs = []
        for group in pairs:
            for a, b in combinations(group, 2):
                key = pair_key(a, b)
                round_pairs.append(key)
                seen.add(key)
        history["rounds"].append({
            "date": date.today().isoformat(),
            "pairs": round_pairs,
            "unmatched": [p["name"] for p in unmatched],
        })
        history["pairs_seen"] = sorted(seen)
        save_history(history)
        print(f"\nSaved round to {HISTORY_FILE}.")


if __name__ == "__main__":
    main()
