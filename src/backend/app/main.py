"""FastAPI entry point: API routers, /api/health and the static UI.

Run from the repository root:

    uvicorn backend.app.main:app --app-dir src --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.assistant import copilot_agent
from backend.app.db import create_db_and_tables, db_has_data
from backend.app.routers import (
    airports,
    assistant,
    automation,
    disruptions,
    flights,
    gates,
    onboarding,
)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    await copilot_agent.start_client()
    try:
        yield
    finally:
        await copilot_agent.stop_client()


app = FastAPI(
    title="CPH Agentic Hack API",
    description="Starter API for CPH Agentic Hack with GitHub Copilot. All data is synthetic.",
    version="0.1.0",
    lifespan=lifespan,
)
# No CORS middleware: the UI is served by this same app, so there is only one origin.


class HealthOut(BaseModel):
    status: str
    db: bool
    copilot_sdk: str


@app.get("/api/health", response_model=HealthOut, tags=["health"])
def health() -> HealthOut:
    """Liveness check used by the header indicator and the smoke tests."""
    return HealthOut(
        status="ok",
        db=db_has_data(),
        copilot_sdk="ready" if copilot_agent.client_ready() else "not-configured",
    )


for router_module in (airports, onboarding, flights, disruptions, gates, automation, assistant):
    app.include_router(router_module.router)

# Mount the UI last so the /api and /docs routes take priority.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
