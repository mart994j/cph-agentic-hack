from fastapi.testclient import TestClient


def test_health_reports_ok_and_seeded_db(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db"] is True
    assert response.json()["copilot_sdk"] in {"ready", "not-configured"}


def test_ui_is_served_at_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "CPH Agentic Hack" in response.text
