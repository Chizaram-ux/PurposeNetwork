"""Web layer for Virtual Coffee Roulette.

pair.py stays the pairing engine and knows nothing about the database or HTTP.
This package adds two adapters around it:

    db + models    Postgres tables for the roster and completed rounds
    adapters       DB rows <-> pair.Participant, and a DB-backed History
    rounds         run a round against the database
    api            FastAPI: read-only pairings, plus sign-up
    cli            init-db, import-legacy and run-round for the GitHub Action

The engine's seams are what make this possible: History is subclassable (as
ForgetfulHistory already showed) and CoffeeRound takes plain Participants.
"""
