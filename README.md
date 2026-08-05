# purposenetwork

**Virtual Coffee Roulette** connects people across the Purpose family of companies — Purpose Unlimited, Purpose Investments, Driven, Harness and Steadyhand. Each round builds coffee-chat groups (a group of three when the count is odd) using a weighted score rather than a plain shuffle, so matches are both interesting and actually schedulable: people from other entities and teams are favoured, availability has to line up, and pairs that have already met are pushed apart.

## How pairing works

Every possible pair is scored, then the script picks the highest-scoring **set** of pairings for the whole round — an exhaustive search up to 14 participants, and a greedy pass above that.

| Signal | Score |
| --- | --- |
| Never paired before | +8 |
| Paired within the last 3 rounds | -4 |
| Different entity | +5 |
| Same entity, different team | +3 |
| Overlapping availability slot | +4 |
| Same chat format (both in-person or both online) | +2 |
| Each topic in common | +2, capped at +4 |
| Leaving someone unmatched | -12 |

The weights are constants at the top of `pair.py`, so a round can be re-tuned by editing them. A small random jitter breaks ties, which keeps an unchanged roster from producing the same pairings every time; use `--seed` when a reproducible result is wanted.

Because unmatched people are penalised heavily, an odd participant is folded into whichever existing pair fits them best, forming a group of three.

## Availability

Availability is normalised to slot codes from `Mon AM` through `Fri PM`, so the raw Microsoft Forms wording can be used as-is:

- `Monday morning`, `Mon AM` and `monday/AM` all become `Mon AM`
- `I am flexible / any time works` expands to every slot
- a bare day such as `Wednesday` expands to `Wed AM` and `Wed PM`
- values can be separated by `;` or `,`

Sharing at least one slot is worth points, and `--require-overlap` makes it mandatory. Anyone left without an overlap is reported as unmatched rather than being put into a chat that cannot be booked.

## Participants file

`participants.csv` has the columns `name`, `entity`, `team`, `format`, `availability`, `topics` and `email`:

```
name,entity,team,format,availability,topics,email
Maya Hollander,Purpose Unlimited,People & Culture,Online,Mon PM;Wed PM;Fri PM,Career journey;What you do at Purpose;Advice,maya.hollander@example.com
```

## Running a round

```
python3 pair.py                     # smart pairing, avoids past pairs
python3 pair.py --require-overlap   # only pair people who share a time slot
python3 pair.py --seed 42           # reproducible tie-breaking
python3 pair.py --explain           # show the score and reasons behind each match
python3 pair.py --no-history        # preview a round without reading or updating history.json
python3 pair.py --emails mail.json  # also write the invitation payload for Power Automate
```

Flags combine, for example `python pair.py --require-overlap --explain`.

### What a round looks like

```
Coffee Roulette pairings for 2026-08-05
4 participants, 2 groups

1. Maya Hollander + Isabella Tang
     Maya Hollander - Purpose Unlimited / People & Culture - free: Mon PM, Wed PM, Fri PM
     Isabella Tang - Purpose Investments / Fund Operations - free: Tue AM, Wed AM
     When:    no shared slot - agree a time by email
     Format:  online (both agree)
     Topics:  no overlap - try "Career journey" or "Future outlooks"
     Score:   3.4 (different entity, no shared slot, both prefer online, met in a recent round)
```

## Files

- `pair.py` — the scoring and pairing script.
- `participants.csv` — the roster: entity, team, chat format, availability and topics.
- `history.json` — completed rounds and every pair already seen. Starts empty and is updated after each round unless `--no-history` is used.
- `docs/automation.md` — how a round runs on its own, and how the emails go out.

## Emailing the pairings

`--emails FILE` writes the round as JSON: one invitation per group, with the
recipients, subject and body already assembled. The scheduled Action writes
`pairings.json` on every run and posts it to a Power Automate flow, which sends
the intros from Outlook. Addresses come from the `email` column; anyone missing
one is reported under `needsEmailAddress` rather than being quietly dropped.
See [docs/automation.md](docs/automation.md) for the flow setup.

## Keeping the roster up to date

Participants sign up through the Purpose-Network Microsoft Form. Because availability is normalised at read time, form answers can be appended to `participants.csv` exactly as the form words them, with no clean-up step in between.
