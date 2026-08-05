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
2. **Export the responses sheet.** Forms gives an Excel copy of every response; save it as CSV with the columns `name,entity,team,format,availability,topics` and replace the file. Better when several people joined at once.
3. **Let a flow write it.** This is what the Power Automate flow was for. It currently fails at the "Get participants file" step with a 404 because the personal access token in the HTTP header cannot see this repository.

Nothing breaks if the roster is stale: the round simply runs with whoever is already listed.

## Fixing the flow

In order of how little they ask of the organisation:

- **Move the roster to Excel Online or a SharePoint list.** Forms writes there through a first-party connector with no token at all, and a workflow step (or a person) refreshes `participants.csv` from that sheet.
- **Use the official GitHub connector** in Power Automate, which authenticates with an org-approved OAuth connection rather than a personal token, if that connector is permitted in the tenant.
- **Keep the API approach** only if a fine-grained token can be issued for this repository, approved for the PurposeAdvisorSolutions organisation and SSO-authorised. Store it in a secure input, never in a plain header.

Whichever route is taken, the token currently sitting in the flow run history should be revoked and replaced, because anyone who can open that run can read it.

## Announcing the pairings

Power Automate is still the right home for the human-facing half. A scheduled flow can pick up the pairings and post them to Teams or send the Outlook intros; that side never needed write access to the repository.
