from fastapi.testclient import TestClient


def test_get_queues_returns_filtered_sorted_slots(client: TestClient) -> None:
    response = client.get("/api/onboarding/queues", params={"terminal": "T3"})

    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert all(row["terminal"] == "T3" for row in rows)
    assert [row["slot_start"] for row in rows] == sorted(row["slot_start"] for row in rows)


def test_get_queues_rejects_reversed_time_window(client: TestClient) -> None:
    response = client.get(
        "/api/onboarding/queues",
        params={"from": "2026-11-24T12:00:00Z", "to": "2026-11-24T11:00:00Z"},
    )

    assert response.status_code == 400


def test_get_forecast_returns_all_checkpoints_for_terminal(client: TestClient) -> None:
    response = client.get("/api/onboarding/forecast", params={"terminal": "T2", "hours": 3})

    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert {row["terminal"] for row in rows} == {"T2"}
    assert {row["checkpoint"] for row in rows} == {"CHECKIN", "SECURITY", "PASSPORT"}
    assert len(rows) <= 36
