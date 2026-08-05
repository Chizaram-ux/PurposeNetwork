"""The HTTP layer.

Rounds are read-only here on purpose: a round is created by the scheduled
GitHub Action calling `python -m app.cli run-round`, so there is exactly one
place where pairings come from. The API's writable surface is sign-up.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import adapters, models, rounds, schemas
from app.db import get_session

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Purpose-Network Coffee Roulette",
    description="Pairings and sign-up for coffee chats across the Purpose family.",
    version="1.0.0",
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/options", response_model=schemas.Options)
def options() -> schemas.Options:
    return schemas.Options.build()


# ------------------------------------------------------------- the roster ---


@app.get("/api/participants", response_model=List[schemas.ParticipantOut])
def list_participants(
    include_inactive: bool = Query(False, description="also return people who have opted out"),
    session: Session = Depends(get_session),
) -> List[schemas.ParticipantOut]:
    query = select(models.Participant).order_by(models.Participant.name)
    if not include_inactive:
        query = query.where(models.Participant.active.is_(True))
    return [schemas.ParticipantOut.of(row) for row in session.scalars(query).all()]


@app.post("/api/participants", response_model=schemas.ParticipantOut,
          status_code=status.HTTP_201_CREATED)
def create_participant(
    payload: schemas.ParticipantIn,
    session: Session = Depends(get_session),
) -> schemas.ParticipantOut:
    slots = payload.slots
    if not slots:
        # 422 as an integer: the Starlette constant for it has been renamed once
        # already, and this way the code does not depend on which name is current.
        raise HTTPException(422, "Pick at least one time slot, or say you are flexible.")

    row = models.Participant(
        name=payload.name,
        entity=payload.entity,
        team=payload.team,
        chat_format=payload.normalised_format,
        email=payload.email,
        availability_raw=adapters.as_raw_text(payload.availability),
        slots=slots,
        topics=payload.normalised_topics,
        active=True,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            payload.name + " is already signed up. Ask People & Culture to update the details.",
        )
    return schemas.ParticipantOut.of(row)


# ------------------------------------------------------------------ rounds --


@app.get("/api/rounds", response_model=List[schemas.RoundSummary])
def list_rounds(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> List[schemas.RoundSummary]:
    recent = rounds.recent_rounds(session, limit)
    counts = rounds.group_counts(session, [row.id for row in recent])
    return [schemas.RoundSummary.of(row, counts[row.id]) for row in recent]


# Declared before /api/rounds/{round_id} so that "current" is not read as an id.
@app.get("/api/rounds/current", response_model=schemas.RoundOut)
def current_round(session: Session = Depends(get_session)) -> schemas.RoundOut:
    row = rounds.latest_round(session)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No round has been run yet.")
    return schemas.RoundOut.of(row)


@app.get("/api/rounds/{round_id}", response_model=schemas.RoundOut)
def one_round(round_id: int, session: Session = Depends(get_session)) -> schemas.RoundOut:
    row = rounds.round_by_id(session, round_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round " + str(round_id) + " not found.")
    return schemas.RoundOut.of(row)


@app.get("/api/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    """Headline numbers for the page banner."""
    people = session.scalar(
        select(func.count()).select_from(models.Participant)
        .where(models.Participant.active.is_(True))
    )
    round_count = session.scalar(select(func.count()).select_from(models.Round))
    connections = len(adapters.all_pair_keys(session))
    return {
        "participants": people or 0,
        "rounds": round_count or 0,
        "connections": connections,
    }


# -------------------------------------------------------------- the front end --

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))
