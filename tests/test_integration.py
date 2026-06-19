"""Integration tests for the gencan-sse pipeline.

End-to-end tests that wire up SpeechEngine with a mock TTS provider,
exercising the real queue → worker → TTS → player pipeline.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from gencan_sse.engine import SpeechEngine
from gencan_sse.config import EngineConfig
from gencan_sse.types import EventType, Priority, SpeakResult


class MockTTSProvider:
    """A mock TTS provider that returns deterministic PCM bytes."""

    def __init__(self, audio_bytes: bytes = b"\x00\x01" * 100):
        self._audio = audio_bytes
        self.calls: list[tuple[str, str, str]] = []

    async def synthesize(self, text: str, voice: str = "Kore", style: str = "") -> bytes:
        self.calls.append((text, voice, style))
        return self._audio

    @property
    def is_available(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "mock-tts"


@pytest.fixture
def mock_provider():
    """Create a fresh MockTTSProvider for each test."""
    return MockTTSProvider()


@pytest.fixture
def engine_config():
    """Minimal engine config for fast tests."""
    return EngineConfig(
        max_queue_depth=10,
        stale_timeout_seconds=30.0,
    )


# ---------------------------------------------------------------------------
# TestEngineLifecycle
# ---------------------------------------------------------------------------


class TestEngineLifecycle:
    """Test start/stop, context manager, and double-start idempotency."""

    @patch("pyaudio.PyAudio")
    def test_start_sets_running(self, mock_pa, mock_provider, engine_config):
        """Engine.start() should set is_running to True."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        try:
            engine.start()
            assert engine.is_running is True
        finally:
            engine.stop()

    @patch("pyaudio.PyAudio")
    def test_stop_clears_running(self, mock_pa, mock_provider, engine_config):
        """Engine.stop() should set is_running to False."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        engine.start()
        engine.stop()
        assert engine.is_running is False

    @patch("pyaudio.PyAudio")
    def test_double_start_is_noop(self, mock_pa, mock_provider, engine_config):
        """Calling start() twice should not raise or create duplicate threads."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        try:
            engine.start()
            worker_thread = engine._worker._thread
            engine.start()  # second call — should be a no-op
            assert engine._worker._thread is worker_thread
            assert engine.is_running is True
        finally:
            engine.stop()

    @patch("pyaudio.PyAudio")
    def test_stop_before_start_is_noop(self, mock_pa, mock_provider, engine_config):
        """Calling stop() on an engine that was never started should not raise."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        engine.stop()  # should not raise
        assert engine.is_running is False

    @patch("pyaudio.PyAudio")
    def test_context_manager(self, mock_pa, mock_provider, engine_config):
        """Engine should support `with` statement: start on enter, stop on exit."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            assert engine.is_running is True
        assert engine.is_running is False


# ---------------------------------------------------------------------------
# TestSpeakQueuing
# ---------------------------------------------------------------------------


class TestSpeakQueuing:
    """Test that speak() queues text and the TTS provider is invoked."""

    @patch("pyaudio.PyAudio")
    def test_speak_returns_queued(self, mock_pa, mock_provider, engine_config):
        """speak() should return a SpeakResult with status='queued'."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            result = engine.speak("Hello, integration test!")
            assert isinstance(result, SpeakResult)
            assert result.status == "queued"

    @patch("pyaudio.PyAudio")
    def test_speak_invokes_provider_synthesize(self, mock_pa, mock_provider, engine_config):
        """After speak(), the mock provider's synthesize() should be called
        with the submitted text (possibly chunked)."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            engine.speak("Hello, world!")
            # Give the background worker time to process
            time.sleep(0.5)

        # The provider should have been called at least once
        assert len(mock_provider.calls) >= 1
        # The spoken text should appear in the synthesize calls
        spoken_texts = [call[0] for call in mock_provider.calls]
        combined = " ".join(spoken_texts)
        assert "Hello" in combined

    @patch("pyaudio.PyAudio")
    def test_speak_with_custom_voice(self, mock_pa, mock_provider, engine_config):
        """speak() with a custom voice should pass that voice to the provider."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            engine.speak("Alert!", voice="Fenrir", style="[alert] ")
            time.sleep(0.5)

        assert len(mock_provider.calls) >= 1
        # Check that the voice and style reached the provider
        voices_used = [call[1] for call in mock_provider.calls]
        styles_used = [call[2] for call in mock_provider.calls]
        assert "Fenrir" in voices_used
        assert "[alert] " in styles_used

    @patch("pyaudio.PyAudio")
    def test_speak_empty_text_skipped(self, mock_pa, mock_provider, engine_config):
        """speak() with empty text should return 'skipped' and not call the provider."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            result = engine.speak("")
            assert result.status == "skipped"
            time.sleep(0.2)

        assert len(mock_provider.calls) == 0

    @patch("pyaudio.PyAudio")
    def test_speak_when_not_running_returns_error(self, mock_pa, mock_provider, engine_config):
        """speak() before start() should return status='error'."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        result = engine.speak("Should fail")
        assert result.status == "error"
        assert "not running" in result.message.lower()

    @patch("pyaudio.PyAudio")
    def test_multiple_speaks_all_queued(self, mock_pa, mock_provider, engine_config):
        """Multiple speak() calls should all return 'queued' and eventually invoke the provider."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            r1 = engine.speak("First sentence.")
            r2 = engine.speak("Second sentence.")
            r3 = engine.speak("Third sentence.")
            assert r1.status == "queued"
            assert r2.status == "queued"
            assert r3.status == "queued"
            time.sleep(1.0)

        # All three should have reached the provider
        assert len(mock_provider.calls) >= 3


# ---------------------------------------------------------------------------
# TestDrainMethod
# ---------------------------------------------------------------------------


class TestDrainMethod:
    """Test the drain() method for waiting on queue completion."""

    @patch("pyaudio.PyAudio")
    def test_drain_empty_queue_returns_true(self, mock_pa, mock_provider, engine_config):
        """drain() on an empty queue should return True immediately."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            result = engine.drain(timeout=2.0)
            assert result is True

    @patch("pyaudio.PyAudio")
    def test_drain_not_running_returns_true(self, mock_pa, mock_provider, engine_config):
        """drain() when the engine is not running should return True."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        result = engine.drain(timeout=1.0)
        assert result is True

    @patch("pyaudio.PyAudio")
    def test_drain_with_short_timeout(self, mock_pa, mock_provider, engine_config):
        """drain() with a very short timeout should return promptly."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            start = time.time()
            result = engine.drain(timeout=0.2)
            elapsed = time.time() - start
            # Should complete in well under 1s (empty queue → immediate True)
            assert result is True
            assert elapsed < 1.0

    @patch("pyaudio.PyAudio")
    def test_drain_after_speak(self, mock_pa, mock_provider, engine_config):
        """drain() after speak() should eventually return True once the queue empties."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            engine.speak("Drain test.")
            result = engine.drain(timeout=5.0)
            assert result is True


# ---------------------------------------------------------------------------
# TestSpeakEvent
# ---------------------------------------------------------------------------


class TestSpeakEvent:
    """Test speak_event() with structured JSON events through the full pipeline."""

    @patch("pyaudio.PyAudio")
    def test_speak_event_message(self, mock_pa, mock_provider, engine_config):
        """A JSON message event should go through classifier → filter → TTS provider."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            event = json.dumps({"type": "message", "content": "Hello from event!"})
            result = engine.speak_event(event)
            assert result.status == "queued"
            time.sleep(0.5)

        # The provider should have been called with text from the event
        assert len(mock_provider.calls) >= 1
        spoken_texts = [call[0] for call in mock_provider.calls]
        combined = " ".join(spoken_texts)
        assert "Hello from event" in combined

    @patch("pyaudio.PyAudio")
    def test_speak_event_error(self, mock_pa, mock_provider, engine_config):
        """An error event should be classified and synthesized."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            event = json.dumps({"type": "error", "message": "Something broke!"})
            result = engine.speak_event(event)
            assert result.status == "queued"
            time.sleep(0.5)

        assert len(mock_provider.calls) >= 1
        spoken_texts = [call[0] for call in mock_provider.calls]
        combined = " ".join(spoken_texts)
        assert "Something broke" in combined

    @patch("pyaudio.PyAudio")
    def test_speak_event_skip_type(self, mock_pa, mock_provider, engine_config):
        """An 'init' event (skip type) should be queued but not reach the TTS provider."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            event = json.dumps({"type": "init", "session_id": "abc123"})
            result = engine.speak_event(event)
            assert result.status == "queued"
            time.sleep(0.5)

        # Skip events should not produce synthesis calls
        assert len(mock_provider.calls) == 0

    @patch("pyaudio.PyAudio")
    def test_speak_event_not_running_returns_error(self, mock_pa, mock_provider, engine_config):
        """speak_event() before start() should return status='error'."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        event = json.dumps({"type": "message", "content": "No engine"})
        result = engine.speak_event(event)
        assert result.status == "error"

    @patch("pyaudio.PyAudio")
    def test_speak_event_tool_use(self, mock_pa, mock_provider, engine_config):
        """A tool_use event should synthesize the tool name announcement."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            event = json.dumps({"type": "tool_use", "tool": "read_file"})
            result = engine.speak_event(event)
            assert result.status == "queued"
            time.sleep(0.5)

        assert len(mock_provider.calls) >= 1
        spoken_texts = [call[0] for call in mock_provider.calls]
        combined = " ".join(spoken_texts)
        assert "read_file" in combined


# ---------------------------------------------------------------------------
# TestPriorityOrdering
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    """Test that priority levels are accepted and items are queued successfully."""

    @patch("pyaudio.PyAudio")
    def test_error_priority_queued(self, mock_pa, mock_provider, engine_config):
        """ERROR priority items should be queued successfully."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            result = engine.speak(
                "Critical error occurred!",
                priority=Priority.ERROR,
                event_type=EventType.ERROR,
            )
            assert result.status == "queued"
            time.sleep(0.5)

        assert len(mock_provider.calls) >= 1

    @patch("pyaudio.PyAudio")
    def test_all_priority_levels_accepted(self, mock_pa, mock_provider, engine_config):
        """All priority levels should be accepted without error."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            for priority in Priority:
                result = engine.speak(
                    f"Testing {priority.name} priority.",
                    priority=priority,
                )
                assert result.status == "queued", (
                    f"Priority {priority.name} was not queued: {result.message}"
                )
            time.sleep(1.0)

        # All four priorities should have been synthesized
        assert len(mock_provider.calls) >= len(Priority)

    @patch("pyaudio.PyAudio")
    def test_error_event_synthesized_via_speak_event(self, mock_pa, mock_provider, engine_config):
        """An error event via speak_event() should be synthesized (errors are never skipped)."""
        mock_pa.return_value = MagicMock()
        engine = SpeechEngine(config=engine_config, tts_provider=mock_provider)
        with engine:
            event = json.dumps({"type": "error", "message": "Fatal crash!"})
            result = engine.speak_event(event)
            assert result.status == "queued"
            time.sleep(0.5)

        assert len(mock_provider.calls) >= 1
        spoken_texts = [call[0] for call in mock_provider.calls]
        combined = " ".join(spoken_texts)
        assert "Fatal crash" in combined
