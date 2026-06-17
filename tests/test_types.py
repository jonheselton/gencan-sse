"""Tests for gencan_sse.types module."""

import time

from gencan_sse.types import (
    AudioChunk,
    ClassifiedEvent,
    EngineStatus,
    EventType,
    Priority,
    SpeakResult,
    VoiceMapping,
)


class TestEventType:
    """Tests for the EventType enum."""

    def test_all_values_exist(self):
        assert EventType.MESSAGE.value == "message"
        assert EventType.THINKING.value == "thinking"
        assert EventType.TOOL_USE.value == "tool_use"
        assert EventType.TOOL_RESULT.value == "tool_result"
        assert EventType.ERROR.value == "error"
        assert EventType.SKIP.value == "skip"

    def test_lookup_by_value(self):
        assert EventType("message") == EventType.MESSAGE
        assert EventType("error") == EventType.ERROR


class TestPriority:
    """Tests for the Priority enum."""

    def test_ordering(self):
        assert Priority.ERROR.value < Priority.RESPONSE.value
        assert Priority.RESPONSE.value < Priority.TOOL.value
        assert Priority.TOOL.value < Priority.THINKING.value

    def test_all_values(self):
        assert Priority.ERROR.value == 1
        assert Priority.RESPONSE.value == 2
        assert Priority.TOOL.value == 3
        assert Priority.THINKING.value == 4


class TestClassifiedEvent:
    """Tests for the ClassifiedEvent dataclass."""

    def test_creation(self):
        event = ClassifiedEvent(
            event_type=EventType.MESSAGE,
            text="hello",
            raw={"type": "message", "content": "hello"},
        )
        assert event.event_type == EventType.MESSAGE
        assert event.text == "hello"
        assert event.priority == Priority.RESPONSE  # default

    def test_custom_priority(self):
        event = ClassifiedEvent(
            event_type=EventType.ERROR,
            text="error",
            raw={},
            priority=Priority.ERROR,
        )
        assert event.priority == Priority.ERROR


class TestAudioChunk:
    """Tests for the AudioChunk dataclass."""

    def test_creation(self):
        chunk = AudioChunk(
            pcm_data=b"\x00" * 100,
            priority=Priority.RESPONSE,
            event_type=EventType.MESSAGE,
        )
        assert len(chunk.pcm_data) == 100
        assert chunk.priority == Priority.RESPONSE
        assert chunk.timestamp > 0

    def test_auto_timestamp(self):
        before = time.time()
        chunk = AudioChunk(
            pcm_data=b"\x00",
            priority=Priority.RESPONSE,
            event_type=EventType.MESSAGE,
        )
        after = time.time()
        assert before <= chunk.timestamp <= after


class TestVoiceMapping:
    """Tests for the VoiceMapping dataclass."""

    def test_defaults(self):
        vm = VoiceMapping(voice_name="Kore")
        assert vm.voice_name == "Kore"
        assert vm.style_prefix == ""
        assert vm.enabled is True
        assert vm.priority == 2

    def test_custom_values(self):
        vm = VoiceMapping(
            voice_name="Fenrir",
            style_prefix="[alert] ",
            enabled=True,
            priority=1,
        )
        assert vm.style_prefix == "[alert] "
        assert vm.priority == 1


class TestSpeakResult:
    """Tests for the SpeakResult dataclass."""

    def test_queued(self):
        result = SpeakResult(status="queued", message="ok", queue_depth=3)
        assert result.status == "queued"
        assert result.queue_depth == 3

    def test_defaults(self):
        result = SpeakResult(status="skipped")
        assert result.message == ""
        assert result.queue_depth == 0


class TestEngineStatus:
    """Tests for the EngineStatus dataclass."""

    def test_creation(self):
        status = EngineStatus(
            is_running=True,
            queue_depth=5,
            volume=0.8,
            speed=1.0,
            uptime_seconds=100.0,
            tts_provider="gemini",
            tts_available=True,
        )
        assert status.is_running is True
        assert status.queue_depth == 5
        assert status.voices == {}
