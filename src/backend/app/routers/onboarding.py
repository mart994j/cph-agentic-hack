"""Passenger onboarding track: queues and wait-time forecasts at CPH checkpoints.

Guide: docs/track-1-passenger-onboarding.md
Data: ``passenger_flow`` (15-minute slots per terminal and checkpoint).
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.app.db import get_session
from backend.app.models import Checkpoint, PassengerFlow, Terminal

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
CPH_TZ = ZoneInfo("Europe/Copenhagen")


class QueueSlotOut(BaseModel):
    terminal: Terminal
    checkpoint: Checkpoint
    slot_start: datetime
    pax_count: int
    avg_wait_min: float


class QueueForecastOut(BaseModel):
    terminal: Terminal
    checkpoint: Checkpoint
    slot_start: datetime
    predicted_wait_min: float


def forecast_waits(
    session: Session,
    terminal: Terminal | None = None,
    checkpoint: Checkpoint = Checkpoint.SECURITY,
    hours: int = 3,
) -> list[dict]:
    """Return read-ahead wait forecasts for the next hours in Copenhagen local time."""
    if hours < 1 or hours > 24:
        raise HTTPException(status_code=422, detail="hours must be between 1 and 24")

    rows = list(session.exec(select(PassengerFlow).order_by(PassengerFlow.slot_start)).all())
    if not rows:
        return []

    distinct_slots = sorted({row.slot_start for row in rows})
    now = datetime.now(UTC)
    future_slots = [slot for slot in distinct_slots if slot >= now]
    slot_count = hours * 4

    if future_slots:
        remaining_slots = [slot for slot in distinct_slots if slot >= future_slots[0]]
        if len(remaining_slots) >= slot_count:
            target_slots = remaining_slots[:slot_count]
        else:
            target_slots = remaining_slots
    else:
        target_slots = distinct_slots[-slot_count:] if len(distinct_slots) >= slot_count else distinct_slots
    target_set = set(target_slots)
    terminals = [terminal] if terminal is not None else [Terminal.T2, Terminal.T3]

    forecasts: list[dict] = []
    for row in rows:
        if row.slot_start not in target_set:
            continue
        if row.terminal not in terminals or row.checkpoint != checkpoint:
            continue
        forecasts.append({
            "terminal": row.terminal.value,
            "checkpoint": row.checkpoint.value,
            "slot_start": row.slot_start,
            "slot_start_local": row.slot_start.astimezone(CPH_TZ).isoformat(timespec="minutes"),
            "predicted_wait_min": round(row.avg_wait_min, 1),
        })

    return sorted(forecasts, key=lambda item: (item["slot_start"], item["terminal"]))


@router.get("/queues", response_model=list[QueueSlotOut])
def get_queues(
    terminal: Terminal | None = Query(default=None, description="T2 or T3; omit for both"),
    from_: datetime | None = Query(default=None, alias="from", description="Start (UTC)"),
    to: datetime | None = Query(default=None, description="End (UTC)"),
    session: Session = Depends(get_session),
) -> list[QueueSlotOut]:
    """Return passenger-flow slots, filtered by terminal and time window."""
    if from_ is not None and to is not None and from_ >= to:
        raise HTTPException(status_code=400, detail="from must be earlier than to")

    statement = select(PassengerFlow).order_by(PassengerFlow.slot_start)
    if terminal is not None:
        statement = statement.where(PassengerFlow.terminal == terminal)
    if from_ is not None:
        statement = statement.where(PassengerFlow.slot_start >= from_)
    if to is not None:
        statement = statement.where(PassengerFlow.slot_start <= to)
    return list(session.exec(statement).all())


@router.get("/forecast", response_model=list[QueueForecastOut])
def get_forecast(
    terminal: Terminal | None = Query(default=None, description="T2 or T3; omit for both"),
    hours: int = Query(default=3, ge=1, le=24, description="Forecast horizon in hours"),
    session: Session = Depends(get_session),
) -> list[QueueForecastOut]:
    """Return a wait-time forecast for the coming hours per terminal and checkpoint."""
    terminals = [terminal] if terminal is not None else [Terminal.T2, Terminal.T3]
    forecasts: list[QueueForecastOut] = []
    for terminal_value in terminals:
        for checkpoint in Checkpoint:
            checkpoint_forecasts = forecast_waits(
                session,
                terminal=terminal_value,
                checkpoint=checkpoint,
                hours=hours,
            )
            for item in checkpoint_forecasts:
                forecasts.append(QueueForecastOut(
                    terminal=Terminal(item["terminal"]),
                    checkpoint=Checkpoint(item["checkpoint"]),
                    slot_start=item["slot_start"],
                    predicted_wait_min=item["predicted_wait_min"],
                ))
    return sorted(forecasts, key=lambda item: (item.slot_start, item.terminal.value, item.checkpoint.value))
