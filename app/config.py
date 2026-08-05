"""Settings, read from the environment.

DATABASE_URL is the only thing that has to be provided in production. Several
hosts hand out `postgres://` URLs and SQLAlchemy 2 wants an explicit driver, so
the URL is normalised rather than trusted as-is.
"""

from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "postgresql+psycopg://localhost/purposenetwork"

# The Purpose family, offered by the sign-up form. Free text is still accepted,
# so a new entity does not need a code change to sign up.
ENTITIES = (
    "Purpose Unlimited",
    "Purpose Investments",
    "Driven",
    "Harness",
    "Steadyhand",
)

FORMATS = ("Online", "In person")

# Every slot from `Mon AM` to `Fri PM` is Toronto time. Written as "Eastern time"
# rather than EST because the rounds run year round, and half of them fall in EDT.
TIMEZONE_LABEL = "Eastern time (ET)"
TIMEZONE_SHORT = "ET"

# Starting points for the topics question; people can add their own.
TOPIC_SUGGESTIONS = (
    "Career journey",
    "What you do at Purpose",
    "What projects you do at Purpose",
    "What led you to your position",
    "Advice",
    "Future outlooks",
    "Finance",
    "Tech",
    "Sports",
)


def normalise_database_url(url: str) -> str:
    """Make any of the common Postgres URL spellings work with psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def database_url() -> str:
    return normalise_database_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
