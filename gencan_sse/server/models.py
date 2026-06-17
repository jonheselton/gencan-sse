"""Pydantic schemas for the REST API."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from gencan_sse.types import Priority, EventType

class SpeakRequest(BaseModel):
    """Payload for POST /speak."""
    text: str = Field(..., description="The text to synthesize and speak.")
    voice: Optional[str] = Field(None, description="The voice name to use (e.g., 'Kore').")
    style: str = Field("", description="Optional style prefix (e.g., '[alert] ').")
    priority: int = Field(Priority.RESPONSE.value, description="Queue priority (lower is higher priority). 1=ERROR, 2=RESPONSE, 3=TOOL.")
    event_type: str = Field(EventType.MESSAGE.value, description="Event classification type.")

class EventRequest(BaseModel):
    """Payload for POST /event."""
    event: Dict[str, Any] = Field(..., description="The structured event JSON to classify and speak.")

class ControlRequest(BaseModel):
    """Payload for POST /control."""
    action: str = Field(..., description="The action to perform (e.g., 'stop', 'set_volume', 'set_speed', 'flush').")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Action-specific parameters.")

class StatusResponse(BaseModel):
    """Response for GET /status."""
    is_running: bool
    queue_depth: int
    tts_available: bool
