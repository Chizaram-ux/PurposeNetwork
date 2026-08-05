# Automation

How a round actually happens, and which parts run without anyone touching them.

## The moving parts

| Piece | Lives in | Responsibility |
| --- | --- | --- |
| Purpose-Network form | Microsoft Forms | collects entity, team, chat format, availability and topics |
| `participants.csv` | this repo | the roster the pairing engine reads |
| `pair.py` | this repo | scores every possible pair and builds the round |
| `history.json` | this repo | every pair already seen, so repeats are avoided |
| `.github/workflows/coffee-roulette.yml` | GitHub Actions | runs the round on a schedule and records it |
| Form-to-roster flow | Power Automate | was meant to append new sign-ups to the roster |

## What runs on its own

The workflow runs every Monday at 13:00 UTC (9am Eastern in summer, 8am in winter) and can also be started by hand from the Actions tab, where it offers a `require_overlap` checkbox and an optional `seed`. Each run checks out the repo, runs `pair.py`, prints the pairings into the run summary, uploads them as a `pairings` artifact, and commits the updated `history.json` as `github-actions[bot]`.

It writes using the built-in `GITHUB_TOKEN` that Actions issues for the duration of the run, so there is no personal access token to create, approve or renew.

To read a round: **Actions** tab, then **Coffee Roulette pairing**, then the latest run. The summary lists each group with entity, team, a suggested time and topics.

## What is still manual

Only the roster. `participants.csv` does not update itself, so new form responses have to reach the file before a round. Three ways, cheapest first.

1. **Paste the new rows.** Open the form results, copy the people who signed up since the last round, and add them to `participants.csv` in the browser. Availability can be pasted exactly as the form words it (`Monday morning`, `I am flexible / any time works`) because the parser normalises it. Takes a minute and needs no tokens.
2. **Export the responses sheet.** Forms gives an Excel copy of every response; save it as CSV with the columns `name,entity,team,format,availability,topics,email` and replace the file. Better when several people joined at once.
3. **Let a flow write it.** This is what the Power Automate flow was for. It currently fails at the "Get participants file" step with a 404 because the personal access token in the HTTP header cannot see this repository.

Nothing breaks if the roster is stale: the round simply runs with whoever is already listed.

## Fixing the flow

In order of how little they ask of the organisation:

- **Move the roster to Excel Online or a SharePoint list.** Forms writes there through a first-party connector with no token at all, and a workflow step (or a person) refreshes `participants.csv` from that sheet.
- **Use the official GitHub connector** in Power Automate, which authenticates with an org-approved OAuth connection rather than a personal token, if that connector is permitted in the tenant.
- **Keep the API approach** only if a fine-grained token can be issued for this repository, approved for the PurposeAdvisorSolutions organisation and SSO-authorised. Store it in a secure input, never in a plain header.

Whichever route is taken, the token currently sitting in the flow run history should be revoked and replaced, because anyone who can open that run can read it.

## Emailing the pairings

Every round now produces two files:

| File | What it is |
| --- | --- |
| `pairings.txt` | the readable report that lands in the run summary |
| `pairings.json` | the same round as one invitation per group, ready to mail |

`pairings.json` is written by `python pair.py --emails pairings.json` and looks like this:

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

Addresses come from the `email` column in `participants.csv`. Anyone without
one is listed under `needsEmailAddress`, so a gap in the roster shows up as a
note to the organiser rather than a silently skipped person.

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
