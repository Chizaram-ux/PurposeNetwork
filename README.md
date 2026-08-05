# purposenetwork

**Virtual Coffee Roulette** connects people across the Purpose family of companies — Purpose Unlimited, Purpose Investments, Driven, Harness and Steadyhand. Each round builds coffee-chat groups (a group of three when the count is odd) using a weighted score rather than a plain shuffle, so matches are both interesting and actually schedulable: people from other entities and teams are favoured, availability has to line up, and pairs that have already met are pushed apart.

There are two halves. `pair.py` is the pairing engine — standard library only, and unaware of anything around it. `app/` is a web app on top: a page where people sign themselves up and read their match, and a FastAPI backend over Postgres. Rounds run automatically every Monday from GitHub Actions, which also hands the invitations to Power Automate to send from Outlook.

## The web app

```bash
pip3 install -r requirements.txt
export DATABASE_URL=postgresql://localhost/purposenetwork

python3 -m app.cli init-db          # create the tables
python3 -m app.cli import-legacy    # load participants.csv and history.json
uvicorn app.api:app --reload        # http://127.0.0.1:8000
```

The page at `/` shows the current round — each group with entity, team, a suggested time, shared topics and an optional "why this match" — plus a sign-up form whose Mon AM–Fri PM grid means availability arrives already structured. Past rounds are readable from the same page.

`pair.py` is untouched by any of this. It still scores, matches and writes the invitation payload; `app/` only supplies it with people from Postgres instead of a CSV and stores what comes back. **Rounds are created in one place only** — the scheduled workflow calling `python3 -m app.cli run-round` — so the API's round endpoints are read-only and a stray request cannot invent a pairing.

| Command | What it does |
| --- | --- |
| `python3 -m app.cli init-db` | create the tables |
| `python3 -m app.cli import-legacy` | migrate `participants.csv` and `history.json` into Postgres |
| `python3 -m app.cli run-round` | run a round and store it |
| `python3 -m app.cli run-round --emails pairings.json` | also write the invitation payload |
| `python3 -m app.cli run-round --dry-run` | preview a round without storing it |
| `python3 -m app.cli show-round [ID]` | print a stored round |

`docs/webapp.md` covers the endpoints, the schema and deployment. Three things to know before sharing a link: the Action needs a `DATABASE_URL` secret, **no authentication is built in yet** so the page belongs behind SSO or on the internal network, and email addresses are deliberately never returned by the API — they are collected at sign-up and used only to build the invitations.

## How pairing works

Every possible pair is scored, then the engine picks the highest-scoring **set** of pairings for the whole round — an exhaustive search up to 14 participants, and a greedy pass above that.

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

Past rounds are not stored twice: "who has already met" is derived by self-joining group membership, so a group of three yields its three pairs and nothing can fall out of step.

## Availability

**All times are Eastern time (ET)** — the whole roster is read in Toronto time, and the page says so on both the sign-up form and the pairing cards. It is written as "Eastern" rather than "EST" because rounds run year round and half of them fall in EDT. The wording lives in `app/config.py` as `TIMEZONE_LABEL`, so it is stated in one place.

Availability is normalised to slot codes from `Mon AM` through `Fri PM`, so raw Microsoft Forms wording can be used as-is:

- `Monday morning`, `Mon AM` and `monday/AM` all become `Mon AM`
- `I am flexible / any time works` expands to every slot
- a bare day such as `Wednesday` expands to `Wed AM` and `Wed PM`
- values can be separated by `;` or `,`

Sharing at least one slot is worth points, and `--require-overlap` makes it mandatory. Anyone left without an overlap is reported as unmatched rather than being put into a chat that cannot be booked.

The sign-up form sends slot codes directly, and the API accepts either those or the old form wording — which is what lets the Microsoft Form keep feeding the app during a transition.

## Running a round from the files

The original file-based path still works, and needs no database. `participants.csv` has the columns `name`, `entity`, `team`, `format`, `availability`, `topics` and `email`:

```
name,entity,team,format,availability,topics,email
Maya Hollander,Purpose Unlimited,People & Culture,Online,Mon PM;Wed PM;Fri PM,Career journey;What you do at Purpose;Advice,maya.hollander@example.com
```

```
python3 pair.py                     # smart pairing, avoids past pairs
python3 pair.py --require-overlap   # only pair people who share a time slot
python3 pair.py --seed 42           # reproducible tie-breaking
python3 pair.py --explain           # show the score and reasons behind each match
python3 pair.py --no-history        # preview a round without reading or updating history.json
python3 pair.py --emails mail.json  # also write the invitation payload for Power Automate
```

Flags combine, for example `python3 pair.py --require-overlap --explain`. The same flags exist on `app.cli run-round`, which reads Postgres instead.

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

## Emailing the pairings

`--emails FILE` writes the round as JSON: one invitation per group, with the
recipients, subject and body already assembled. The scheduled Action writes
`pairings.json` on every run and posts it to a Power Automate flow, which sends
the intros from Outlook. Anyone missing an address is reported under
`needsEmailAddress` rather than being quietly dropped.

Addresses come from the `email` column when a round runs from the files, and from
the sign-up form's email field when it runs from Postgres. Either way the payload
is identical, so the flow does not care which path ran. A `--dry-run` skips the
mail step entirely. See [docs/automation.md](docs/automation.md) for the flow setup.

## Tests

```bash
python3 -m pytest
```

The suite runs on SQLite, so it needs no database server: the list columns in `app/models.py` are Postgres arrays with a JSON variant for SQLite.

## Files

- `pair.py` — the scoring and pairing engine, and the invitation payload. Standard library only, and unaware of the database.
- `app/` — the web app: `api.py` (HTTP), `models.py` (Postgres), `adapters.py` (rows ⇄ engine), `rounds.py` (run and read rounds), `cli.py` (commands), `static/index.html` (the page).
- `tests/` — the suite, which runs on SQLite and needs no database server.
- `participants.csv`, `history.json` — the original file-based store. Still what `python3 pair.py` reads, and what `import-legacy` migrates from.
- `docs/webapp.md` — setting the app up, the endpoints and deployment.
- `docs/automation.md` — how a round runs on its own, and how the emails go out.

## Keeping the roster up to date

Sign-ups go through the form on the page — name, company, team, work email and availability — and land in Postgres, so there is nothing to keep in step by hand. The Microsoft Form can still feed the app if it stays: availability is normalised at read time, so form wording can be posted to `/api/participants` exactly as written. See `docs/automation.md`.
