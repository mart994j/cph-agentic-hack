"""CPH Ops Assistant chat endpoint, backed by the Copilot SDK.

Guide: docs/assistant-and-finale.md
The chat drawer in the UI switches on automatically once this stops returning 501.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.assistant import copilot_agent

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatIn(BaseModel):
    # No min_length on purpose: the UI probes with an empty message. Once implemented,
    # reject empty messages with a 400 (any non-501 answer switches the chat drawer on).
    message: str = Field(max_length=4000)
    session_id: str | None = None


class ChatOut(BaseModel):
    reply: str
    session_id: str


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn) -> ChatOut:
    """Send the user's message to the CPH Ops Assistant and return its reply."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message must not be empty")
    if not copilot_agent.client_ready():
        raise HTTPException(status_code=503, detail="Copilot SDK client is not running")
    reply, session_id = await copilot_agent.ask(body.message.strip(), body.session_id)
    return ChatOut(reply=reply, session_id=session_id)
