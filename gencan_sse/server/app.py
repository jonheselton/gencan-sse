"""FastAPI application for the GenCan SSE daemon."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from gencan_sse.engine import SpeechEngine
from gencan_sse.types import Priority, EventType
from gencan_sse.server.models import SpeakRequest, EventRequest, ControlRequest, StatusResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the lifecycle of the SpeechEngine."""
    logger.info("Starting SpeechEngine daemon...")
    engine = SpeechEngine()
    engine.start()
    app.state.engine = engine
    yield
    logger.info("Stopping SpeechEngine daemon...")
    engine.stop()


def get_engine(request: Request) -> SpeechEngine:
    """Retrieve the SpeechEngine from application state."""
    return request.app.state.engine


# Initialize FastAPI with the lifespan
app = FastAPI(
    title="GenCan Speech Synthesis Engine",
    description="A standalone daemon service for async TTS queueing and audio playback.",
    version="0.1.0",
    lifespan=lifespan,
)

# -------------------------------------------------------------------------
# Dashboard UI
# -------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def redirect_to_dashboard():
    """Redirect root to the dashboard."""
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
async def serve_dashboard():
    """Serve the monitoring dashboard HTML page."""
    try:
        dashboard_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "dashboard.html"
        )
        with open(dashboard_path, "r") as f:
            content = f.read()
        return HTMLResponse(content)
    except Exception as e:
        logger.error("Failed to read dashboard.html: %s", e)
        return HTMLResponse("<h1>Error loading dashboard UI</h1>", status_code=500)


# -------------------------------------------------------------------------
# REST API — Speak & Events
# -------------------------------------------------------------------------

@app.post("/speak", summary="Speak raw text")
async def speak(request: SpeakRequest, req: Request):
    """Synthesize and speak raw text. Returns the queue depth."""
    engine = get_engine(req)
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
async def process_event(request: EventRequest, req: Request):
    """Process a structured event (e.g. from an LLM stream) for filtering, classification, and speech."""
    engine = get_engine(req)
    import json
    result = engine.speak_event(json.dumps(request.event))
    return {"status": result.status, "queue_depth": result.queue_depth}


@app.post("/control", summary="Control the audio player")
async def control(request: ControlRequest, req: Request):
    """Send control actions to the engine (e.g., stop, flush, set_volume, set_speed)."""
    engine = get_engine(req)
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
async def get_status(req: Request):
    """Retrieve the current running status of the engine."""
    engine = get_engine(req)
    status = engine.status()
    return StatusResponse(
        is_running=status.is_running,
        queue_depth=status.queue_depth,
        tts_available=status.tts_available,
    )


# -------------------------------------------------------------------------
# Dashboard API — /api/* endpoints for the monitoring UI
# -------------------------------------------------------------------------

@app.get("/api/status", summary="Extended status for dashboard")
async def api_status(req: Request):
    """Returns full engine status including voices, usage, and circuit breaker state."""
    engine = get_engine(req)
    status = engine.status()

    # Build voice routing map for the dashboard
    voices_data = {}
    if status.voices:
        # voices is a dict of EventType.name -> voice_name from engine.status()
        # We need to expand it to include style and enabled for the dashboard
        for etype_name, voice_name in status.voices.items():
            voices_data[etype_name] = {
                "voice": voice_name,
                "style": "",
                "enabled": True,
            }
        # Try to get richer data from the voice_map
        try:
            for etype, (name, style, enabled) in engine._voice_map.items():
                voices_data[etype.name] = {
                    "voice": name,
                    "style": style,
                    "enabled": enabled,
                }
        except Exception:
            pass

    return JSONResponse({
        "queue_depth": status.queue_depth,
        "volume": status.volume,
        "speed": status.speed,
        "uptime_seconds": int(status.uptime_seconds),
        "tts_available": status.tts_available,
        "tts_circuit_open": False,  # TODO: wire to provider circuit breaker
        "tts_cooldown_remaining": 0,
        "audio_output_mode": "local",
        "voices": voices_data,
        "usage": status.usage,
    })


@app.get("/api/logs", summary="Get activity logs")
async def api_logs(req: Request):
    """Returns the activity log for the live feed."""
    engine = get_engine(req)
    return JSONResponse({"logs": engine.get_activity_log()})


@app.post("/api/speak", summary="Speak text (dashboard)")
async def api_speak(req: Request):
    """Speak text from the dashboard sandbox."""
    engine = get_engine(req)
    data = await req.json()
    text = data.get("text", "")
    voice = data.get("voice", "Kore")
    style = data.get("style", "")
    if not text.strip():
        return JSONResponse({"status": "error", "message": "Empty text"}, status_code=400)
    result = engine.speak(text=text, voice=voice, style=style)
    return JSONResponse({"status": "success", "message": f"Queued (depth={result.queue_depth})"})


@app.post("/api/volume", summary="Set volume (dashboard)")
async def api_volume(req: Request):
    """Adjust playback volume from the dashboard."""
    engine = get_engine(req)
    data = await req.json()
    volume = float(data.get("volume", 0.8))
    engine.set_volume(volume)
    return JSONResponse({"status": "success", "message": f"Volume set to {volume:.0%}"})


@app.post("/api/speed", summary="Set speed (dashboard)")
async def api_speed(req: Request):
    """Adjust playback speed from the dashboard."""
    engine = get_engine(req)
    data = await req.json()
    speed = float(data.get("speed", 1.0))
    engine.set_speed(speed)
    return JSONResponse({"status": "success", "message": f"Speed set to {speed:.2f}x"})


@app.post("/api/stop", summary="Stop audio (dashboard)")
async def api_stop(req: Request):
    """Stop current playback from the dashboard."""
    engine = get_engine(req)
    engine.stop_audio()
    return JSONResponse({"status": "success", "message": "Audio stopped"})


@app.post("/api/flush", summary="Flush queue (dashboard)")
async def api_flush(req: Request):
    """Flush the audio queue from the dashboard."""
    engine = get_engine(req)
    data = await req.json()
    event_type = data.get("event_type", "")
    engine.flush_queue(event_type)
    return JSONResponse({"status": "success", "message": "Queue flushed"})


@app.post("/api/voice", summary="Update voice routing (dashboard)")
async def api_voice(req: Request):
    """Update voice routing configuration from the dashboard."""
    engine = get_engine(req)
    data = await req.json()
    event_type_name = data.get("event_type", "")
    voice_name = data.get("voice_name", "")
    style_prefix = data.get("style_prefix", "")
    enabled = bool(data.get("enabled", True))

    # Update the voice routing in memory
    try:
        etype = EventType[event_type_name.upper()]
        if etype in engine._voice_map:
            engine._voice_map[etype] = (voice_name, style_prefix, enabled)
        engine.set_voice(event_type_name, voice_name)
        return JSONResponse({"status": "success", "message": f"Voice for {event_type_name} set to {voice_name}"})
    except KeyError:
        return JSONResponse({"status": "error", "message": f"Unknown event type: {event_type_name}"}, status_code=400)


@app.post("/api/service/restart", summary="Restart daemon")
async def api_service_restart(req: Request):
    """Restart the daemon process (relies on launchd KeepAlive to restart)."""
    logger.info("Service restart requested via dashboard API")

    async def do_exit():
        await asyncio.sleep(0.5)
        os._exit(0)

    asyncio.create_task(do_exit())
    return JSONResponse({"status": "success", "message": "Service is restarting..."})


@app.post("/api/service/stop", summary="Stop daemon")
async def api_service_stop(req: Request):
    """Stop and unload the daemon process."""
    logger.info("Service stop requested via dashboard API")

    async def do_stop():
        await asyncio.sleep(0.5)
        import subprocess
        is_dev = os.environ.get("GENCAN_DEV") == "true"
        plist_name = "com.gencan.sse.dev.plist" if is_dev else "com.gencan.sse.plist"
        plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{plist_name}")
        try:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", plist_path])
        except Exception:
            # Fallback: just exit the process
            os._exit(0)

    asyncio.create_task(do_stop())
    return JSONResponse({"status": "success", "message": "Service is stopping and unloading..."})
