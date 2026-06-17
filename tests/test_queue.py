"""Tests for gencan_sse.queue module."""

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from gencan_sse.queue import (
    SpeakMessage,
    EventMessage,
    ControlMessage,
    PlaybackWorker,
)
from gencan_sse.types import EventType, Priority


class TestSpeakMessage:
    """Tests for SpeakMessage dataclass."""

    def test_defaults(self):
        msg = SpeakMessage(text="hello")
        assert msg.text == "hello"
        assert msg.voice == "Kore"
        assert msg.style == ""
        assert msg.priority == Priority.RESPONSE
        assert msg.event_type == EventType.MESSAGE
        assert msg.timestamp > 0

    def test_custom_values(self):
        msg = SpeakMessage(
            text="alert",
            voice="Fenrir",
            style="[alert] ",
            priority=Priority.ERROR,
            event_type=EventType.ERROR,
        )
        assert msg.voice == "Fenrir"
        assert msg.priority == Priority.ERROR


class TestEventMessage:
    """Tests for EventMessage dataclass."""

    def test_creation(self):
        msg = EventMessage(event_json='{"type": "message"}')
        assert msg.event_json == '{"type": "message"}'
        assert msg.timestamp > 0


class TestControlMessage:
    """Tests for ControlMessage dataclass."""

    def test_stop(self):
        msg = ControlMessage(action="stop")
        assert msg.action == "stop"
        assert msg.payload == {}

    def test_set_volume(self):
        msg = ControlMessage(action="set_volume", payload={"volume": 0.5})
        assert msg.payload["volume"] == 0.5


class TestPlaybackWorker:
    """Tests for PlaybackWorker."""

    def _make_worker(self):
        """Create a PlaybackWorker with mocked dependencies."""
        tts = MagicMock()
        tts.name = "mock"
        tts.is_available = True
        tts.synthesize = AsyncMock(return_value=b"\x00" * 100)

        player = MagicMock()
        player._sample_rate = 24000
        player._heap = []
        player._lock = asyncio.Lock()
        player.enqueue = AsyncMock()
        player.play_loop = AsyncMock()
        player.stop = AsyncMock()

        text_filter = MagicMock()
        text_filter.filter.return_value = "filtered text"

        voice_map = {
            EventType.MESSAGE: ("Kore", "", True),
            EventType.ERROR: ("Fenrir", "[alert] ", True),
        }

        return PlaybackWorker(
            tts_provider=tts,
            audio_player=player,
            text_filter=text_filter,
            voice_map=voice_map,
        )

    def test_not_running_initially(self):
        worker = self._make_worker()
        assert worker.is_running is False

    def test_queue_depth_initially_zero(self):
        worker = self._make_worker()
        assert worker.queue_depth == 0

    def test_submit_increases_depth(self):
        worker = self._make_worker()
        worker.submit(SpeakMessage(text="hello"))
        assert worker.queue_depth >= 1

    def test_submit_returns_depth(self):
        worker = self._make_worker()
        depth = worker.submit(SpeakMessage(text="hello"))
        assert depth >= 1
