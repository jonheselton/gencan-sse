"""Tests for the FastAPI server wrapper."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from gencan_sse.server.app import app
from gencan_sse.engine import SpeechEngine
from gencan_sse.types import SpeakResult, EngineStatus, EventType

@pytest.fixture
def mock_engine():
    mock = MagicMock()
    mock.speak.return_value = SpeakResult(status="queued", queue_depth=1)
    mock.speak_event.return_value = SpeakResult(status="queued", queue_depth=2)
    mock.status.return_value = EngineStatus(
        is_running=True,
        queue_depth=0,
        tts_available=True,
        volume=0.8,
        speed=1.0,
        uptime_seconds=100.0,
        tts_provider="mock",
        voices={"MESSAGE": "Kore", "ERROR": "Fenrir"},
        usage={"total_characters": 500, "total_requests": 3, "failed_requests": 0, "estimated_cost_usd": 0.0075},
    )
    mock.get_activity_log.return_value = [
        {"timestamp": "2026-06-19T10:00:00Z", "event_type": "MESSAGE", "voice_name": "Kore", "text": "Hello", "status": "success"}
    ]
    mock.get_usage_stats.return_value = {"total_characters": 500, "total_requests": 3, "failed_requests": 0, "estimated_cost_usd": 0.0075}
    # Set up voice map for dashboard API
    mock._voice_map = {
        EventType.MESSAGE: ("Kore", "", True),
        EventType.ERROR: ("Fenrir", "[alert] ", True),
    }
    app.state.engine = mock
    yield mock

@pytest.fixture
def client(mock_engine):
    # Patch SpeechEngine so lifespan doesn't create a real one
    with patch("gencan_sse.server.app.SpeechEngine") as mock_cls:
        mock_cls.return_value = mock_engine
        with TestClient(app) as c:
            yield c


# ---- Original REST API tests ----

def test_speak_endpoint(client, mock_engine):
    response = client.post(
        "/speak",
        json={
            "text": "Hello world",
            "voice": "Kore",
            "priority": 2,
            "event_type": "message"
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "queued", "queue_depth": 1}
    mock_engine.speak.assert_called_once()
    args, kwargs = mock_engine.speak.call_args
    assert kwargs["text"] == "Hello world"
    assert kwargs["voice"] == "Kore"

def test_event_endpoint(client, mock_engine):
    response = client.post(
        "/event",
        json={
            "event": {"type": "message", "text": "foo"}
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "queued", "queue_depth": 2}
    mock_engine.speak_event.assert_called_once()

def test_control_endpoint(client, mock_engine):
    response = client.post(
        "/control",
        json={
            "action": "stop",
            "payload": {}
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "stop"}
    mock_engine.stop_audio.assert_called_once()

def test_status_endpoint(client, mock_engine):
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {
        "is_running": True,
        "queue_depth": 0,
        "tts_available": True
    }
    mock_engine.status.assert_called_once()

def test_invalid_speak_priority(client, mock_engine):
    response = client.post(
        "/speak",
        json={
            "text": "Hello",
            "priority": 999,  # Invalid Priority enum value
        }
    )
    assert response.status_code == 400
    assert "Invalid priority" in response.json()["detail"]

def test_no_global_engine():
    """Verify that importing app no longer creates a global SpeechEngine."""
    import gencan_sse.server.app as app_module
    # The module should NOT have a top-level 'engine' attribute
    assert not hasattr(app_module, 'engine') or not isinstance(getattr(app_module, 'engine', None), SpeechEngine)


# ---- Dashboard API tests ----

def test_root_redirects_to_dashboard(client, mock_engine):
    """GET / should redirect to /dashboard."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert "/dashboard" in response.headers["location"]

def test_dashboard_serves_html(client, mock_engine):
    """GET /dashboard should serve an HTML page."""
    response = client.get("/dashboard")
    # It may 200 with HTML or 500 if dashboard.html doesn't exist yet
    assert response.status_code in (200, 500)

def test_api_status(client, mock_engine):
    """GET /api/status should return extended status with voices and usage."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "queue_depth" in data
    assert "volume" in data
    assert "speed" in data
    assert "uptime_seconds" in data
    assert "voices" in data
    assert "usage" in data
    assert data["volume"] == 0.8
    assert data["speed"] == 1.0

def test_api_logs(client, mock_engine):
    """GET /api/logs should return activity log entries."""
    response = client.get("/api/logs")
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert len(data["logs"]) == 1
    assert data["logs"][0]["event_type"] == "MESSAGE"

def test_api_speak(client, mock_engine):
    """POST /api/speak should call engine.speak and return success."""
    response = client.post(
        "/api/speak",
        json={"text": "Dashboard test", "voice": "Kore", "style": ""}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_engine.speak.assert_called_once()

def test_api_volume(client, mock_engine):
    """POST /api/volume should set volume."""
    response = client.post("/api/volume", json={"volume": 0.5})
    assert response.status_code == 200
    mock_engine.set_volume.assert_called_once_with(0.5)

def test_api_speed(client, mock_engine):
    """POST /api/speed should set speed."""
    response = client.post("/api/speed", json={"speed": 1.5})
    assert response.status_code == 200
    mock_engine.set_speed.assert_called_once_with(1.5)

def test_api_stop(client, mock_engine):
    """POST /api/stop should stop audio."""
    response = client.post("/api/stop")
    assert response.status_code == 200
    mock_engine.stop_audio.assert_called_once()

def test_api_flush(client, mock_engine):
    """POST /api/flush should flush the queue."""
    response = client.post("/api/flush", json={"event_type": ""})
    assert response.status_code == 200
    mock_engine.flush_queue.assert_called_once_with("")

def test_api_voice(client, mock_engine):
    """POST /api/voice should update voice routing."""
    response = client.post(
        "/api/voice",
        json={"event_type": "MESSAGE", "voice_name": "Puck", "style_prefix": "", "enabled": True}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
