"""CPH Ops Assistant: Copilot SDK skeleton (NOT wired up yet).

The plan
--------
1. One ``CopilotClient`` is started once, when the app starts, from the FastAPI
   ``lifespan`` in ``backend/app/main.py`` (``start_client``) and stopped on shutdown.
2. Each chat conversation gets its own Copilot *session*. ``POST /api/assistant/chat``
   calls ``ask(message, session_id)``; the session id is returned to the UI so the next
   message continues the same conversation.
3. Each track exposes one read-only app function as a Copilot SDK *tool* (for example
   ``get_flights_at_risk``, ``get_active_disruptions`` or ``get_pax_connections``). The
   model calls these tools to answer questions about CPH operations.

Rules
-----
* The SDK is **optional at start-up**. Import it lazily inside functions so the app runs
  even when the SDK, the runtime or a Copilot sign-in is missing.
* Pinned package: ``github-copilot-sdk==1.0.34`` (public preview). Use ONLY the API in the
  official README for that version: https://github.com/github/copilot-sdk/tree/main/python
  (now hosted at https://github.com/microsoft/copilot-sdk), plus the repo's
  ``.github/instructions/copilot-sdk-python.instructions.md`` and the
  ``.github/skills/copilot-sdk-tool`` skill.
* Tools must be read-only and must never return personal data. All data is synthetic.

Guide: docs/assistant-and-finale.md
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from backend.app.db import engine
from backend.app.models import Checkpoint, Direction, FlightStatus, Terminal
from backend.app.routers.flights import flights_for_assistant
from backend.app.routers.onboarding import forecast_waits

SYSTEM_MESSAGE = """\
You are the CPH Ops Assistant, an operations co-pilot for Copenhagen Airport (CPH).
You help duty managers understand flights, passenger queues, disruptions, stands and
transfer baggage. Use the provided tools for facts; never invent flight data. Answer
briefly, use local Copenhagen time, and say which tool your answer is based on.
All data in this system is synthetic workshop data."""

_client: Any | None = None  # the running CopilotClient, once started
_sessions: dict[str, Any] = {}  # chat session id -> Copilot session
logger = logging.getLogger(__name__)


class QueueForecastParams(BaseModel):
    """Parameters for the passenger queue forecast tool."""

    terminal: Terminal | None = Field(default=None, description="Terminal T2 or T3; omit for both")
    checkpoint: Checkpoint = Field(default=Checkpoint.SECURITY, description="Checkpoint to forecast")
    hours: int = Field(default=3, ge=1, le=24, description="Forecast horizon in hours")


class FlightsParams(BaseModel):
    """Parameters for the upcoming flight search tool."""

    direction: Direction | None = Field(default=None, description="DEP or ARR; omit for both")
    hours_ahead: int = Field(default=2, ge=1, le=24, description="Look-ahead window in hours")
    status: FlightStatus | None = Field(default=None, description="Optional exact flight status filter")


def sdk_installed() -> bool:
    """Return True when the ``copilot`` package can be imported (no runtime check)."""
    return importlib.util.find_spec("copilot") is not None


async def start_client() -> None:
    """Start the shared Copilot client. Call once from the FastAPI lifespan."""
    global _client
    if _client is not None:
        return
    try:
        from copilot import CopilotClient

        client = CopilotClient()
        await client.start()
        _client = client
    except Exception:
        logger.warning("Copilot SDK did not start; the rest of the app remains available", exc_info=True)


async def stop_client() -> None:
    """Stop the shared Copilot client on shutdown (safe to call when it never started)."""
    global _client
    client = _client
    _client = None
    sessions = list(_sessions.values())
    _sessions.clear()
    try:
        for session in sessions:
            await session.disconnect()
    finally:
        if client is not None:
            await client.stop()


def client_ready() -> bool:
    """Return whether the shared Copilot SDK client is running."""
    return _client is not None


def build_tools() -> list[Any]:
    """Return the Copilot SDK tools exposed to the assistant. Empty until tracks add theirs."""
    if not sdk_installed():
        return []

    try:
        from copilot import define_tool

        @define_tool(
            name="get_queue_forecast",
            description="Return the CPH passenger queue wait forecast for a terminal and checkpoint. "
                        "Times are Europe/Copenhagen and waits are minutes.",
            skip_permission=True,
        )
        async def get_queue_forecast(params: QueueForecastParams) -> str:
            """Return compact JSON for passenger queue forecasts."""
            with Session(engine) as session:
                forecasts = forecast_waits(
                    session,
                    terminal=params.terminal,
                    checkpoint=params.checkpoint,
                    hours=params.hours,
                )
                return json.dumps(forecasts[:50], default=str)

        @define_tool(
            name="get_flights",
            description="List upcoming CPH arrivals or departures, optionally filtered by status. "
                        "Times are Europe/Copenhagen; results are synthetic and limited to 50 flights.",
            skip_permission=True,
        )
        async def get_flights(params: FlightsParams) -> str:
            """Return compact JSON for upcoming flights."""
            try:
                with Session(engine) as session:
                    flights = flights_for_assistant(
                        session,
                        direction=params.direction,
                        hours_ahead=params.hours_ahead,
                        status=params.status,
                    )
                return json.dumps(flights, default=str)
            except SQLAlchemyError:
                logger.exception("Could not retrieve flight data for the assistant")
                return json.dumps({"error": "Flight data is temporarily unavailable"})

        return [get_queue_forecast, get_flights]
    except (ImportError, RuntimeError):
        return []


async def ask(message: str, session_id: str | None = None) -> tuple[str, str]:
    """Send ``message`` to the assistant and return ``(reply_text, session_id)``."""
    if _client is None:
        raise RuntimeError("Copilot SDK client is not running")

    session = _sessions.get(session_id) if session_id else None
    if session is None:
        from copilot import PermissionRequestResult

        def reject_non_app_tools(request: Any, invocation: Any) -> Any:
            return PermissionRequestResult(kind="denied-interactively-by-user")

        session = await _client.create_session(
            on_permission_request=reject_non_app_tools,
            model=os.environ.get("COPILOT_MODEL") or None,
            system_message={"mode": "append", "content": SYSTEM_MESSAGE},
            tools=build_tools(),
        )
        session_id = session.session_id or str(uuid4())
        _sessions[session_id] = session

    event = await session.send_and_wait(message, timeout=60)
    reply = event.data.content if event is not None and event.data is not None else "No reply was returned."
    return reply, session_id
