# purposenetwork

**Virtual Coffee Roulette** connects people across the Purpose family of companies — Purpose Unlimited (PU), Purpose Investments (PI), Driven, and Harness. Each round randomly pairs participants (with a group of three when the count is odd) for an informal coffee chat, deliberately favoring matches outside your immediate team so interns and colleagues get to meet people they wouldn't otherwise cross paths with. The tool remembers past pairings so repeats are avoided across rounds, and it can optionally restrict matches to people who share an availability slot.

## How it works

Participants live in `participants.csv` with the columns: `name`, `entity`, `team`, `format`, `availability`, and `topics`. Availability slots and topics are each semicolon-separated (for example, `Mon PM;Wed PM;Fri PM`). Every time you run a round, the script prints the pairings and appends them to `history.json`, which tracks completed rounds and every pair that has already been matched.

## Running a round

Make sure `participants.csv` is up to date, then run one of the following from the repository root:

```
python pair.py                     # random pairing, avoids past pairs (default)
python pair.py --require-overlap    # only pair people who share an availability slot
python pair.py --seed 42            # reproducible shuffle for a fixed result
python pair.py --no-history         # preview a round without reading or updating history.json
```

By default pairing is fully random (it still avoids repeating past pairs). Add `--require-overlap` when you want to guarantee that matched people have a common time slot. Flags can be combined, e.g. `python pair.py --require-overlap --seed 42`.

## Files

- `pair.py` — the pairing script.
- `participants.csv` — the roster of participants and their availability and topics.
- `history.json` — completed rounds and the set of pairs already seen. Starts empty and is updated automatically after each round.
