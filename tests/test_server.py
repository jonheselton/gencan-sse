"""Tests for the FastAPI server wrapper."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from gencan_sse.server.app import app
from gencan_sse.types import SpeakResult, EngineStatus

@pytest.fixture
def mock_engine():
    with patch("gencan_sse.server.app.engine") as mock:
        # Set up default mock returns
        mock.speak.return_value = SpeakResult(status="queued", queue_depth=1)
        mock.speak_event.return_value = SpeakResult(status="queued", queue_depth=2)
        mock.status.return_value = EngineStatus(
            is_running=True, 
            queue_depth=0, 
            tts_available=True,
            volume=1.0,
            speed=1.0,
            uptime_seconds=100.0,
            tts_provider="mock"
        )
        yield mock

@pytest.fixture
def client():
    # TestClient triggers the lifespan events on instantiation and start of with-block
    with TestClient(app) as c:
        yield c

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
