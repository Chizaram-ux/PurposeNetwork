# The web app

A front end for people signing up and reading their match, and a FastAPI backend
over Postgres. The pairing engine in `pair.py` is unchanged: it still knows
nothing about HTTP or the database, and still runs from files if you want it to.

## How the pieces fit

```
browser ──► app/static/index.html      pairings page + sign-up form
              │  fetch /api/...
              ▼
           app/api.py                  FastAPI: read-only rounds, POST sign-up
              │
              ├─► app/rounds.py        run a round, read rounds back
              │      │
              │      ▼
              │   pair.py              scoring, matching, reporting (untouched)
              │      ▲
              ├─► app/adapters.py      rows ⇄ pair.Participant, DatabaseHistory
              ▼
           Postgres                    roster + every round ever run

GitHub Actions ──► python -m app.cli run-round   (weekly, same engine)
```

Two rules keep this honest:

- **Rounds are created in one place only.** The API cannot create a round; the
  scheduled `run-round` command does. So there is no way for a stray request to
  invent a pairing.
- **History is derived, not duplicated.** "Who has already met" comes from a
  self-join on group membership, so it cannot drift from what actually happened.
  A group of three yields its three pairs for free.

## Setting it up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

createdb purposenetwork                                    # or use a hosted database
export DATABASE_URL=postgresql://localhost/purposenetwork

python -m app.cli init-db          # create the tables
python -m app.cli import-legacy    # load participants.csv and history.json
uvicorn app.api:app --reload       # http://127.0.0.1:8000
```

`DATABASE_URL` accepts `postgres://`, `postgresql://` or
`postgresql+psycopg://`; the first two are rewritten for psycopg 3.

`import-legacy` is a one-off. It loads the CSV roster, then rebuilds the rounds
from `history.json` — that file only stored `"A | B"` pair keys, so groups are
recovered by taking connected components of each round's pair graph. Anyone who
appears in the history but not on the roster is kept as an inactive participant,
so their past pairs still count as "already met". Re-running it refuses to
import history twice unless you pass `--force`.

## Commands

```bash
python -m app.cli init-db                        # create tables
python -m app.cli import-legacy [--force]        # migrate the files into Postgres
python -m app.cli run-round                      # run a round and store it
python -m app.cli run-round --dry-run            # preview without storing
python -m app.cli run-round --explain --seed 42  # as in pair.py
python -m app.cli run-round --emails mail.json   # also write the invitation payload
python -m app.cli show-round [ROUND_ID]          # print a stored round
```

`--emails` calls the same `pair.write_invitations` that `pair.py --emails` uses,
built from the same reports, so the Power Automate mail flow receives an
identical payload whichever path ran. See `docs/automation.md`.

`--dry-run` still consults history, so a preview avoids re-pairing people who
have just met. `--no-history` is the stronger form from `pair.py`: ignore past
rounds entirely.

Any command takes `--database-url` to override the environment for one run.

## The API

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/` | the pairings page and sign-up form |
| GET | `/api/health` | liveness |
| GET | `/api/options` | entities, formats, slots, timezone label and topic suggestions for the form |
| GET | `/api/participants` | the roster (`?include_inactive=true` for everyone) |
| POST | `/api/participants` | sign up; 409 if the name is already taken |
| GET | `/api/rounds` | recent rounds, newest first |
| GET | `/api/rounds/current` | the latest round in full |
| GET | `/api/rounds/{id}` | one round in full |
| GET | `/api/stats` | participants, rounds and connections made |

Interactive docs are at `/docs`.

Sign-up accepts availability either as slot codes from the checkbox grid
(`["Mon AM", "Wed PM"]`) or as raw Microsoft Forms wording
(`"Monday morning; I am flexible"`). Both go through the same normaliser, which
is why the old form can keep feeding the app during a transition.

**Slots are Eastern time.** The wording lives in `app/config.py` as
`TIMEZONE_LABEL` / `TIMEZONE_SHORT` and reaches the page through `/api/options`,
so the form legend and the pairing cards cannot disagree with each other. It says
"Eastern time (ET)" rather than "EST" because rounds run year round and half of
them fall in EDT.

**Email addresses go in but never come out.** Sign-up accepts an optional
`email`, which is used only to build the invitation payload the mail flow sends.
No response body contains an address: `/api/participants` reports `has_email`
instead, and the round endpoints omit it entirely. That is deliberate, because
the page is unauthenticated.

## Deploying

1. Provision Postgres and set `DATABASE_URL` on the web service.
2. Run `python -m app.cli init-db` once against that database.
3. Serve with `uvicorn app.api:app --host 0.0.0.0 --port $PORT`.
4. Add `DATABASE_URL` as a GitHub Actions secret so the weekly workflow can
   reach the same database. Without it the workflow fails with a clear message
   rather than running against nothing.

**There is no authentication.** The page lists colleagues' names, teams and
availability, and anyone who can reach it can add a participant. Put it behind
the corporate SSO proxy or on the internal network before sharing the link. If
it ever needs to be internet-facing, that is the next piece of work, along with
rate limiting on sign-up.

Schema changes are applied with `init-db`, which only creates what is missing.
Anything beyond additive changes (renaming or dropping a column) will want a
real migration tool such as Alembic.

## Tests

```bash
python -m pytest
```

The suite runs on SQLite, so it needs no database server: the list columns in
`app/models.py` are declared as Postgres arrays with a JSON variant for SQLite.
That is a deliberate trade — anything genuinely Postgres-specific has to be
checked against a real database instead.
