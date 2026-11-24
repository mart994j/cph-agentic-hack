from fastapi.testclient import TestClient

from backend.app.assistant import copilot_agent


def test_chat_rejects_empty_message(client: TestClient) -> None:
    response = client.post("/api/assistant/chat", json={"message": "  "})

    assert response.status_code == 400


def test_chat_returns_503_when_sdk_is_unavailable(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(copilot_agent, "client_ready", lambda: False)

    response = client.post("/api/assistant/chat", json={"message": "List flights"})

    assert response.status_code == 503


def test_chat_returns_reply_and_session_id(client: TestClient, monkeypatch) -> None:
    async def fake_ask(message: str, session_id: str | None = None) -> tuple[str, str]:
        assert message == "List flights"
        assert session_id == "existing-session"
        return "There are two upcoming flights.", "existing-session"

    monkeypatch.setattr(copilot_agent, "client_ready", lambda: True)
    monkeypatch.setattr(copilot_agent, "ask", fake_ask)

    response = client.post(
        "/api/assistant/chat",
        json={"message": "  List flights  ", "session_id": "existing-session"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "There are two upcoming flights.",
        "session_id": "existing-session",
    }
