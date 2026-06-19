"""Tests for gencan_sse.engine module (SpeechEngine facade)."""

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from gencan_sse.engine import SpeechEngine, _build_voice_map
from gencan_sse.config import EngineConfig
from gencan_sse.types import EventType, Priority, SpeakResult, EngineStatus


class TestBuildVoiceMap:
    """Tests for _build_voice_map()."""

    def test_default_config(self):
        config = EngineConfig()
        voice_map = _build_voice_map(config)
        assert EventType.MESSAGE in voice_map
        assert EventType.ERROR in voice_map
        assert EventType.THINKING in voice_map
        assert EventType.TOOL_USE in voice_map
        assert EventType.TOOL_RESULT in voice_map

    def test_voice_names(self):
        config = EngineConfig()
        voice_map = _build_voice_map(config)
        name, style, enabled = voice_map[EventType.MESSAGE]
        assert name == "Kore"
        assert enabled is True

    def test_disabled_voice(self):
        config = EngineConfig()
        voice_map = _build_voice_map(config)
        _, _, enabled = voice_map[EventType.TOOL_RESULT]
        assert enabled is False


class TestSpeechEngineInit:
    """Tests for SpeechEngine initialization."""

    def test_create_default(self):
        with patch.dict("os.environ", {}, clear=True):
            engine = SpeechEngine()
            assert engine._config is not None
            assert engine.is_running is False

    def test_create_with_config(self):
        config = EngineConfig(volume=0.5, speed=1.5)
        with patch.dict("os.environ", {}, clear=True):
            engine = SpeechEngine(config=config)
            assert engine._config.volume == 0.5
            assert engine._config.speed == 1.5

    def test_create_with_custom_provider(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)
        assert engine._tts_provider is mock_provider


class TestSpeechEngineSpeakNotRunning:
    """Tests for speak() when engine is not running."""

    def test_speak_before_start(self):
        with patch.dict("os.environ", {}, clear=True):
            engine = SpeechEngine()
            result = engine.speak("hello")
            assert result.status == "error"
            assert "not running" in result.message.lower()

    def test_speak_event_before_start(self):
        with patch.dict("os.environ", {}, clear=True):
            engine = SpeechEngine()
            result = engine.speak_event('{"type": "message", "content": "hi"}')
            assert result.status == "error"


class TestSpeechEngineSpeakRunning:
    """Tests for speak() when engine is running (mocked worker)."""

    def test_speak_empty_text(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        # Manually set running state and mock the worker
        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True

        result = engine.speak("")
        assert result.status == "skipped"

    def test_speak_whitespace(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True

        result = engine.speak("   ")
        assert result.status == "skipped"

    def test_speak_valid_text(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True
        engine._worker.submit.return_value = 1

        result = engine.speak("Hello world")
        assert result.status == "queued"
        assert result.queue_depth == 1
        engine._worker.submit.assert_called_once()

    def test_speak_with_custom_voice(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True
        engine._worker.submit.return_value = 1

        result = engine.speak("Hello", voice="Fenrir", style="[alert] ")
        assert result.status == "queued"
        call_args = engine._worker.submit.call_args[0][0]
        assert call_args.voice == "Fenrir"
        assert call_args.style == "[alert] "


class TestSpeechEngineControls:
    """Tests for engine control methods."""

    def test_set_volume(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        engine._is_running = True
        engine._worker = MagicMock()

        engine.set_volume(0.5)
        assert engine._config.volume == 0.5
        engine._worker.submit.assert_called_once()

    def test_set_volume_clamped(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        engine._is_running = True
        engine._worker = MagicMock()

        engine.set_volume(1.5)
        assert engine._config.volume == 1.0

        engine.set_volume(-0.5)
        assert engine._config.volume == 0.0

    def test_set_speed(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        engine._is_running = True
        engine._worker = MagicMock()

        engine.set_speed(1.5)
        assert engine._config.speed == 1.5


class TestSpeechEngineStatus:
    """Tests for engine status."""

    def test_status(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        status = engine.status()
        assert isinstance(status, EngineStatus)
        assert status.tts_provider == "mock"
        assert status.tts_available is True
        assert status.is_running is False

    def test_status_uses_player_properties(self):
        """status() should use AudioPlayer's public properties."""
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)
        # Set specific values on the player's public properties
        engine._player = MagicMock()
        engine._player.queue_depth = 3
        engine._player.volume = 0.7
        engine._player.speed = 1.5
        engine._start_time = 100.0
        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True
        status = engine.status()
        assert status.queue_depth == 3
        assert status.volume == 0.7
        assert status.speed == 1.5


class TestSpeechEngineContextManager:
    """Tests for context manager protocol."""

    def test_context_manager(self):
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)

        # Mock the worker to avoid threading
        engine._worker = MagicMock()
        engine._worker.is_running = True

        with engine:
            assert engine._is_running is True

        # stop() should have been called
        engine._worker.stop.assert_called_once()


class TestSpeechEngineDrain:
    """Tests for the drain() method."""

    def test_drain_not_running(self):
        """drain() should return True immediately when engine is not running."""
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)
        assert engine.drain(timeout=1.0) is True

    def test_drain_empty_queue(self):
        """drain() should return True when queue is already empty."""
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)
        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True
        # Mock player with queue_depth = 0
        engine._player = MagicMock()
        engine._player.queue_depth = 0
        assert engine.drain(timeout=1.0) is True

    def test_drain_timeout(self):
        """drain() should return False when timeout expires with items still queued."""
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.is_available = True
        engine = SpeechEngine(tts_provider=mock_provider)
        engine._is_running = True
        engine._worker = MagicMock()
        engine._worker.is_running = True
        # Mock player with non-zero queue_depth (always has items)
        engine._player = MagicMock()
        engine._player.queue_depth = 5
        # Use a very short timeout so the test runs fast
        assert engine.drain(timeout=0.3) is False
