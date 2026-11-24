from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.app.db import engine
from backend.app.assistant.copilot_agent import build_tools, sdk_installed
from backend.app.models import Direction, Flight, FlightStatus, Terminal
from backend.app.routers.flights import flights_for_assistant


def test_list_flights_filters_direction_and_sorts_by_schedule(client: TestClient) -> None:
    response = client.get("/api/flights", params={"direction": "DEP"})

    assert response.status_code == 200
    flights = response.json()
    assert flights
    assert all(flight["direction"] == "DEP" for flight in flights)
    assert [flight["sched_time"] for flight in flights] == sorted(
        flight["sched_time"] for flight in flights
    )


def test_list_flights_filters_scheduled_time_window(client: TestClient) -> None:
    all_flights = client.get("/api/flights").json()
    first = all_flights[0]
    later = next(flight for flight in all_flights if flight["sched_time"] > first["sched_time"])

    response = client.get(
        "/api/flights",
        params={"from": first["sched_time"], "to": later["sched_time"]},
    )

    assert response.status_code == 200
    flights = response.json()
    assert flights
    assert all(first["sched_time"] <= flight["sched_time"] <= later["sched_time"] for flight in flights)


def test_list_flights_rejects_reversed_time_window(client: TestClient) -> None:
    response = client.get(
        "/api/flights",
        params={"from": "2026-11-24T12:00:00Z", "to": "2026-11-24T11:00:00Z"},
    )

    assert response.status_code == 400


def test_get_routes_returns_geojson_with_cph_coordinates(client: TestClient) -> None:
    response = client.get("/api/flights/routes")

    assert response.status_code == 200
    collection = response.json()
    assert collection["type"] == "FeatureCollection"
    assert collection["features"]
    for feature in collection["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "LineString"
        start, end = feature["geometry"]["coordinates"]
        assert start == [12.656, 55.6179]
        assert len(end) == 2
        assert feature["properties"]["flights"] > 0
        assert feature["properties"]["status"] in {"ON_TIME", "DELAYED", "CANCELLED"}


def test_flights_for_assistant_returns_local_time_and_other_airport() -> None:
    with Session(engine) as session:
        session.add(Flight(
            flight_no="TEST123",
            airline="SK",
            direction=Direction.DEP,
            origin_iata="CPH",
            dest_iata="FRA",
            sched_time=datetime.now(UTC) + timedelta(minutes=30),
            status=FlightStatus.SCHEDULED,
            terminal=Terminal.T2,
            gate=None,
            aircraft_type="A320",
            pax_count=100,
        ))
        session.flush()
        result = flights_for_assistant(session, direction=Direction.DEP, hours_ahead=1)
        flight = next(item for item in result if item["flight_no"] == "TEST123")

        assert flight["other_airport"] == "FRA"
        assert flight["city"] == "Frankfurt"
        assert datetime.fromisoformat(flight["local_time"]).tzinfo is not None
        assert flight["status"] == "SCHEDULED"
        session.rollback()


@pytest.mark.skipif(not sdk_installed(), reason="Copilot SDK is optional")
def test_build_tools_registers_flight_search_schema() -> None:
    tools = build_tools()

    assert "get_flights" in {tool.name for tool in tools}
    flight_tool = next(tool for tool in tools if tool.name == "get_flights")
    assert {"direction", "hours_ahead", "status"} <= set(flight_tool.parameters["properties"])
