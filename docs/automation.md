# Automation

How a round actually happens, and which parts run without anyone touching them.

## The moving parts

| Piece | Lives in | Responsibility |
| --- | --- | --- |
| Sign-up form | `app/static/index.html` | collects entity, team, chat format, work email, availability and topics |
| Postgres | your database host | the roster and every round ever run |
| `pair.py` | this repo | scores every possible pair, builds the round, writes the invitations |
| `app/` | this repo | the API, the page, and the database adapters |
| `.github/workflows/coffee-roulette.yml` | GitHub Actions | runs the round on a schedule and posts the invitations |
| Mail flow | Power Automate | receives `pairings.json` and sends the intros from Outlook |
| `participants.csv`, `history.json` | this repo | the original file-based store, kept for reference |

## What runs on its own

The workflow runs every Monday at 13:00 UTC (9am Eastern in summer, 8am in
winter) and can also be started by hand from the Actions tab, where it offers a
`require_overlap` checkbox, an optional `seed` and a `dry_run` checkbox. Each run
installs the dependencies and calls:

```bash
python -m app.cli run-round --source github-action --emails pairings.json
```

That command pairs whoever is active in Postgres, stores the round, prints the
pairings into the run summary, writes the invitation payload and uploads both as
a `pairings` artifact. Because the round is written to the database, nothing is
committed back to the repository and the workflow only needs `contents: read`.

A `dry_run` still prints and uploads the preview, but stores nothing and skips
the mail step, so nobody is emailed about a round that did not happen.

The one thing it needs is a `DATABASE_URL` secret (**Settings → Secrets and
variables → Actions**). A run without it stops immediately with an error saying
so, rather than pairing nobody.

To read a round: the page at `/` shows the latest one, and the **Actions** tab
keeps the plain-text version of every run.

## What is still manual

Almost nothing. Sign-ups write straight to Postgres through the form on the
page, so there is no roster file to keep up to date and no copy-paste step
before a round.

What remains is judgement, not typing:

- Deciding when to re-run a round with a different `seed`, or with
  `require_overlap` on, after looking at a `dry_run` preview.
- Removing someone who has left. There is no admin UI yet, so set their `active`
  flag to false in the database: `UPDATE participants SET active = false WHERE
  name = '...'`. Their past pairs still count as "already met", which is why the
  row is deactivated rather than deleted.
- Editing someone's availability or adding a missing email address, which are the
  same kind of one-line update. `needsEmailAddress` in `pairings.json` says who
  is missing one.

The last two are the obvious next slice of work: an admin console that previews a
round before publishing it, and lets People & Culture edit the roster.

## The Microsoft Form and Power Automate

The form can be retired in favour of the page, but it does not have to be. Two
routes if it stays:

- **Point the flow at the API.** A Power Automate HTTP action can `POST` each new
  response to `/api/participants`. Availability may be passed exactly as the form
  words it — `Monday morning`, `I am flexible / any time works` — because the API
  runs the same normaliser the CSV parser used.
- **Keep collecting in Forms and add people by hand** until the page is the only
  route in.

Either way, the personal access token that used to sit in the flow's HTTP header
is no longer needed for pairing, and the copy in the flow run history should be
revoked: anyone who can open that run can read it.

## Emailing the pairings

Every round now produces two files:

| File | What it is |
| --- | --- |
| `pairings.txt` | the readable report that lands in the run summary |
| `pairings.json` | the same round as one invitation per group, ready to mail |

`pairings.json` is written by `--emails pairings.json`, on either
`python pair.py` or `python -m app.cli run-round`, and looks like this:

```json
{
  "round": "2026-08-10",
  "groups": 1,
  "invitations": [
    {
      "group": 1,
      "names": ["Maya Hollander", "Chizaram Agbanelo"],
      "to": ["maya.hollander@example.com", "chizaram.agbanelo@example.com"],
      "missingEmail": [],
      "subject": "Coffee Roulette: Maya Hollander + Chizaram Agbanelo",
      "body": "Hi Maya Hollander, Chizaram Agbanelo - you have been matched ...",
      "when": "Wed PM",
      "format": "online (all agree)",
      "topics": []
    }
  ],
  "unmatched": [],
  "needsEmailAddress": []
}
```

Addresses come from the `email` column in `participants.csv` when a round runs
from the files, and from the sign-up form's email field when it runs from
Postgres. The payload is identical either way, so the flow does not care which
path ran. Anyone without an address is listed under `needsEmailAddress`, so a gap
in the roster shows up as a note to the organiser rather than a silently skipped
person.

Addresses go in and out through this payload only. The API never returns them —
`/api/participants` reports a `has_email` flag instead — because the page is
unauthenticated, and a public list of colleagues' addresses is a different thing
from a public list of names.

### The flow that sends them

The original design had Power Automate reach into GitHub for the roster, which
needed a token the flow was never going to be allowed to hold - that is the
call that returned 404. The mail path reverses the direction: the Action pushes
the finished round to the flow, so nothing on the Microsoft side needs GitHub
credentials.

1. Create a flow with the trigger **When an HTTP request is received** and let
   Power Automate generate the request schema from the sample payload above.
2. Add **Apply to each** over `invitations`.
3. Inside the loop, add **Send an email (V2)**:
   - **To**: `join(item()?['to'], ';')`
   - **Subject**: `item()?['subject']`
   - **Body**: `replace(item()?['body'], decodeUriComponent('%0A'), '<br>')`
4. After the loop, add one more **Send an email (V2)** to the organiser that
   includes `needsEmailAddress` and `unmatched`, so gaps are visible each week.
5. Save the flow and copy the HTTP POST URL from the trigger card.
6. In the repository, open Settings, then Secrets and variables, then Actions,
   and add a secret named `COFFEE_FLOW_URL` holding that URL.

The workflow step that posts the payload skips itself when the secret is
missing, so rounds keep running while the flow is still being built. The same
payload can drive a Teams post instead of, or as well as, the emails.

## Announcing the pairings

Power Automate is still the right home for the human-facing half. The pairing
engine decides who meets whom and writes the invitation text; the flow decides
how it reaches people. Neither half needs write access to the other.

For anything that is not the weekly mail — a Teams post, a reminder a day later —
a flow can also read `/api/rounds/current` instead of waiting to be handed the
payload. That endpoint carries the groups, times and topics, but no addresses.
