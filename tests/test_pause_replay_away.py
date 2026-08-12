"""Tests for Pause, Replay, Away Mode, Spoken History, and Summarizer features."""

import pytest
from gencan_sse.history import SpokenHistoryBuffer, HistoryItem
from gencan_sse.summarizer import generate_catchup_summary
from gencan_sse.engine import SpeechEngine
from gencan_sse.audio_player import AudioPlayer


def test_spoken_history_buffer():
    history = SpokenHistoryBuffer(capacity=5)
    assert history.total_count == 0
    assert history.unread_count == 0

    # Add normal items
    history.add_item(HistoryItem(text="Hello 1", was_away=False))
    history.add_item(HistoryItem(text="Hello 2", was_away=True))
    assert history.total_count == 2
    assert history.unread_count == 1

    # Capacity overflow test
    for i in range(3, 10):
        history.add_item(HistoryItem(text=f"Hello {i}", was_away=True))

    assert history.total_count == 5
    unread = history.get_unread()
    assert len(unread) > 0

    # Mark all read
    history.mark_all_read()
    assert history.unread_count == 0


def test_event_summarizer():
    # Empty case
    empty_summary = generate_catchup_summary([])
    assert "No new updates" in empty_summary

    # Items with messages and errors
    items = [
        HistoryItem(text="Running read_file", event_type="tool_use"),
        HistoryItem(text="Analysis finished", event_type="message"),
        HistoryItem(text="FileNotFoundError: config.json missing", event_type="error"),
    ]
    summary = generate_catchup_summary(items)
    assert "3 updates" in summary or "3 update" in summary
    assert "error" in summary
    assert "FileNotFoundError" in summary


def test_audio_player_pause_and_away():
    player = AudioPlayer()
    assert not player.is_paused
    assert not player.is_away

    player.pause()
    assert player.is_paused

    player.resume()
    assert not player.is_paused

    player.set_away_mode(True)
    assert player.is_away

    player.set_away_mode(False)
    assert not player.is_away


def test_engine_pause_replay_away():
    class DummyProvider:
        name = "dummy"
        is_available = True
        async def synthesize(self, text, voice="Kore", style=""):
            return b"dummy_pcm_audio_data_12345", {}

    engine = SpeechEngine(tts_provider=DummyProvider())
    engine.start()

    try:
        engine.set_away_mode(True)
        assert engine.is_away

        res = engine.speak("Test away speech")
        assert res.status == "queued"
        assert engine.history.unread_count == 1

        # Test catch-up summary
        summary_text = engine.get_catchup_summary()
        assert "1 update" in summary_text

        # Test replay
        replay_res = engine.replay(count=1, unread_only=True)
        assert replay_res.status == "ok"
        assert engine.history.unread_count == 0

        engine.pause()
        assert engine.is_paused
        engine.resume()
        assert not engine.is_paused

    finally:
        engine.stop()
