"""FastAPI application for the GenCan SSE daemon."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from gencan_sse.engine import SpeechEngine
from gencan_sse.types import Priority, EventType
from gencan_sse.server.models import SpeakRequest, EventRequest, ControlRequest, StatusResponse

logger = logging.getLogger(__name__)

# Global engine instance
engine = SpeechEngine()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the lifecycle of the SpeechEngine."""
    logger.info("Starting SpeechEngine daemon...")
    engine.start()
    yield
    logger.info("Stopping SpeechEngine daemon...")
    engine.stop()

# Initialize FastAPI with the lifespan
app = FastAPI(
    title="GenCan Speech Synthesis Engine",
    description="A standalone daemon service for async TTS queueing and audio playback.",
    version="0.1.0",
    lifespan=lifespan,
)

@app.post("/speak", summary="Speak raw text")
async def speak(request: SpeakRequest):
    """Synthesize and speak raw text. Returns the queue depth."""
    try:
        priority = Priority(request.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {request.priority}")
        
    try:
        event_type = EventType(request.event_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {request.event_type}")

    result = engine.speak(
        text=request.text,
        voice=request.voice,
        style=request.style,
        priority=priority,
        event_type=event_type,
    )
    return {"status": result.status, "queue_depth": result.queue_depth}

@app.post("/event", summary="Process a structured event")
async def process_event(request: EventRequest):
    """Process a structured event (e.g. from an LLM stream) for filtering, classification, and speech."""
    import json
    result = engine.speak_event(json.dumps(request.event))
    return {"status": result.status, "queue_depth": result.queue_depth}

@app.post("/control", summary="Control the audio player")
async def control(request: ControlRequest):
    """Send control actions to the engine (e.g., stop, flush, set_volume, set_speed)."""
    action = request.action
    if action == "stop":
        engine.stop_audio()
    elif action == "flush":
        engine.flush_queue(request.payload.get("event_type", ""))
    elif action == "set_volume":
        engine.set_volume(float(request.payload.get("volume", 0.8)))
    elif action == "set_speed":
        engine.set_speed(float(request.payload.get("speed", 1.0)))
    elif action == "set_voice":
        engine.set_voice(request.payload.get("event_type", ""), request.payload.get("voice_name", ""))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown control action: {action}")
    
    return {"status": "ok", "action": request.action}

@app.get("/status", response_model=StatusResponse, summary="Get engine status")
async def get_status():
    """Retrieve the current running status of the engine."""
    status = engine.status()
    return StatusResponse(
        is_running=status.is_running,
        queue_depth=status.queue_depth,
        tts_available=status.tts_available,
    )
