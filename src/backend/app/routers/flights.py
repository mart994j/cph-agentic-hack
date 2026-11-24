"""Flight plans track: departures, arrivals and the route network from CPH.

Guide: docs/track-2-flight-plans.md
Data: ``flight`` joined with ``airport`` for coordinates.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.app.db import get_session
from backend.app.models import Airport, Direction, Flight, FlightStatus

router = APIRouter(prefix="/api/flights", tags=["flights"])
CPH_TZ = ZoneInfo("Europe/Copenhagen")


class FlightOut(BaseModel):
    id: int
    flight_no: str
    airline: str
    direction: Direction
    origin_iata: str
    dest_iata: str
    sched_time: datetime
    est_time: datetime | None
    status: FlightStatus
    terminal: str
    gate: str | None


class RouteCollectionOut(BaseModel):
    """A GeoJSON FeatureCollection of LineString features (one per route from CPH)."""

    type: str = "FeatureCollection"
    features: list[dict[str, Any]]


def flights_for_assistant(
    session: Session,
    direction: Direction | None = None,
    hours_ahead: int = 2,
    status: FlightStatus | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return upcoming synthetic flights with local time and the other airport."""
    if not 1 <= hours_ahead <= 24:
        raise HTTPException(status_code=422, detail="hours_ahead must be between 1 and 24")
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")

    now = datetime.now(UTC)
    statement = (
        select(Flight)
        .where(Flight.sched_time >= now, Flight.sched_time <= now + timedelta(hours=hours_ahead))
        .order_by(Flight.sched_time)
        .limit(limit)
    )
    if direction is not None:
        statement = statement.where(Flight.direction == direction)
    if status is not None:
        statement = statement.where(Flight.status == status)

    airports = {airport.iata: airport for airport in session.exec(select(Airport)).all()}
    results: list[dict[str, Any]] = []
    for flight in session.exec(statement).all():
        other_iata = flight.dest_iata if flight.direction == Direction.DEP else flight.origin_iata
        airport = airports.get(other_iata)
        sched_time = flight.sched_time
        if sched_time.tzinfo is None:
            sched_time = sched_time.replace(tzinfo=UTC)
        results.append({
            "flight_no": flight.flight_no,
            "direction": flight.direction.value,
            "local_time": sched_time.astimezone(CPH_TZ).isoformat(timespec="minutes"),
            "other_airport": other_iata,
            "city": airport.city if airport else other_iata,
            "status": flight.status.value,
            "gate": flight.gate,
        })
    return results


@router.get("", response_model=list[FlightOut])
def list_flights(
    direction: Direction | None = Query(default=None, description="DEP or ARR; omit for both"),
    from_: datetime | None = Query(default=None, alias="from", description="Start (UTC)"),
    to: datetime | None = Query(default=None, description="End (UTC)"),
    session: Session = Depends(get_session),
) -> list[FlightOut]:
    """Return flights filtered by direction and scheduled-time window, sorted by time."""
    if from_ is not None and to is not None and from_ >= to:
        raise HTTPException(status_code=400, detail="from must be earlier than to")

    statement = select(Flight).order_by(Flight.sched_time)
    if direction is not None:
        statement = statement.where(Flight.direction == direction)
    if from_ is not None:
        statement = statement.where(Flight.sched_time >= from_)
    if to is not None:
        statement = statement.where(Flight.sched_time <= to)
    return list(session.exec(statement).all())


@router.get("/routes", response_model=RouteCollectionOut)
def get_routes(session: Session = Depends(get_session)) -> RouteCollectionOut:
    """Return the CPH route network as GeoJSON for the world map."""
    flights = list(session.exec(select(Flight).order_by(Flight.sched_time)).all())
    airports = {airport.iata: airport for airport in session.exec(select(Airport)).all()}
    cph = airports.get("CPH")
    if not flights or cph is None:
        return RouteCollectionOut(features=[])

    grouped: dict[str, list[Flight]] = {}
    for flight in flights:
        other_iata = flight.dest_iata if flight.direction == Direction.DEP else flight.origin_iata
        grouped.setdefault(other_iata, []).append(flight)

    features: list[dict[str, Any]] = []
    for dest_iata, route_flights in sorted(grouped.items()):
        destination = airports.get(dest_iata)
        if destination is None:
            continue
        delayed = sum(flight.status == FlightStatus.DELAYED for flight in route_flights)
        cancelled = sum(flight.status == FlightStatus.CANCELLED for flight in route_flights)
        status = "CANCELLED" if cancelled else "DELAYED" if delayed else "ON_TIME"
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[cph.lon, cph.lat], [destination.lon, destination.lat]],
            },
            "properties": {
                "dest_iata": dest_iata,
                "city": destination.city,
                "lat": destination.lat,
                "lon": destination.lon,
                "flights": len(route_flights),
                "delayed": delayed,
                "cancelled": cancelled,
                "status": status,
            },
        })
    return RouteCollectionOut(features=features)
