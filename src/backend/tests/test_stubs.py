"""Every track endpoint starts as a 501 stub.

When you implement an endpoint, REMOVE its row from STUBS below and add real tests for it
(use the `/write-tests` prompt). A green run means: every remaining stub still says which
HACK(<track>) marker to work on.
"""

import pytest
from fastapi.testclient import TestClient

STUBS = [
    ("GET", "/api/disruptions/active", None, "disruptions"),
    ("GET", "/api/disruptions/1/impact", None, "disruptions"),
    ("GET", "/api/gates/allocations", None, "gates"),
    ("GET", "/api/gates/conflicts", None, "gates"),
    ("GET", "/api/baggage/at-risk", None, "gates"),
    ("POST", "/api/automation/actions", {"action_type": "NOTIFY", "payload": {}}, "disruptions"),
    ("GET", "/api/automation/actions", None, "disruptions"),
]


@pytest.mark.parametrize(("method", "path", "body", "track"), STUBS)
def test_stub_returns_501_with_hack_marker(
    client: TestClient, method: str, path: str, body: dict | None, track: str
) -> None:
    response = client.request(method, path, json=body)

    assert response.status_code == 501
    assert response.json()["detail"].startswith(f"HACK({track}):")
