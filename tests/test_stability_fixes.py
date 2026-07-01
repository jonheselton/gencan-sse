"""Unit tests verifying stability, safety, and security fixes."""

import sys
import asyncio
import threading
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from gencan_sse.filters import TextFilter
from gencan_sse.wav_generator import wrap_pcm_to_wav
from gencan_sse.providers.avfoundation import AVFoundationTTSProvider
from gencan_sse.audio_player import AudioPlayer, _PriorityEntry
from gencan_sse.types import AudioTask, Priority, EventType


def test_wav_generator_invalid_params():
    """Verify that wav_generator raises ValueError on invalid sample parameters."""
    with pytest.raises(ValueError):
        wrap_pcm_to_wav(b"pcm_bytes", sample_rate=0)
    with pytest.raises(ValueError):
        wrap_pcm_to_wav(b"pcm_bytes", sample_width=0)
    with pytest.raises(ValueError):
        wrap_pcm_to_wav(b"pcm_bytes", channels=-1)


def test_text_filter_auto_reset():
    """Verify that TextFilter auto-resets after 30 consecutive empty outputs."""
    filt = TextFilter(dedupe_size=5)
    
    # 1. Trigger code block mode
    filt.filter("```python")
    assert filt._in_code_block is True
    
    # 2. Feed 29 empty messages - should stay in code block
    for _ in range(29):
        filt.filter("print('inside')")
        assert filt._in_code_block is True
        
    # 3. Feed the 30th empty message - should trigger auto-reset to False
    filt.filter("print('last')")
    assert filt._in_code_block is False


@pytest.mark.asyncio
async def test_avfoundation_subprocess_timeout():
    """Verify that AVFoundationTTSProvider handles subprocess timeouts gracefully."""
    provider = AVFoundationTTSProvider()
    provider._available = True
    
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await provider._synthesize_subprocess("Hello", "Zoe")
        assert res == b""
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once()


@pytest.mark.asyncio
async def test_priority_inversion_preemption():
    """Verify that enqueuing a lower-priority task does not preempt a higher-priority task."""
    player = AudioPlayer()
    player.init_async_primitives()
    
    # Mock synthesis tasks
    task1 = asyncio.Future()  # Higher priority (TOOL)
    task2 = asyncio.Future()  # Lower priority (THINKING)
    
    at1 = AudioTask(task=task1, priority=Priority.TOOL, event_type=EventType.TOOL_USE)
    at2 = AudioTask(task=task2, priority=Priority.THINKING, event_type=EventType.THINKING)
    
    # Enqueue task1
    await player.enqueue(at1)
    
    # Start play_loop in a task
    loop_task = asyncio.create_task(player.play_loop())
    
    # Yield control to let play_loop pop task1 and begin awaiting it
    await asyncio.sleep(0.02)
    
    # Now, enqueue task2 (lower priority)
    await player.enqueue(at2)
    await asyncio.sleep(0.02)
    
    # Task1 should NOT be preempted/cancelled
    assert not task1.cancelled()
    
    # Clean up
    await player.stop()
    try:
        await loop_task
    except Exception:
        pass


@pytest.mark.asyncio
async def test_heap_resilience():
    """Verify that heap remains resilient when eviction raises an exception."""
    player = AudioPlayer(max_queue_depth=2)
    player.init_async_primitives()
    
    t1 = AudioTask(task=asyncio.Future(), priority=Priority.RESPONSE, event_type=EventType.MESSAGE)
    t2 = AudioTask(task=asyncio.Future(), priority=Priority.RESPONSE, event_type=EventType.MESSAGE)
    
    await player.enqueue(t1)
    await player.enqueue(t2)
    
    # Mock comparison operator to throw ValueError on eviction
    with patch.object(_PriorityEntry, "__lt__", side_effect=ValueError("LT Error")):
        t3 = AudioTask(task=asyncio.Future(), priority=Priority.RESPONSE, event_type=EventType.MESSAGE)
        with pytest.raises(ValueError):
            await player.enqueue(t3)
            
    # The heap is reassigned atomically, so player._heap should still be valid and uncorrupted
    assert len(player._heap) == 2
    assert player._heap[0].audio_task == t1


def test_cli_port_parsing():
    """Verify that passing --portability does not match --port in cli.py."""
    from gencan_sse.cli import main
    
    test_argv = ["gencan-server", "--dev", "--portability"]
    with patch.object(sys, "argv", test_argv):
        with patch("argparse.ArgumentParser.parse_args") as mock_parse:
            mock_args = MagicMock()
            mock_args.dev = True
            mock_args.port = 8765
            mock_args.log_level = "info"
            mock_parse.return_value = mock_args
            
            with patch("uvicorn.run") as mock_uvicorn:
                try:
                    main()
                except SystemExit:
                    pass
                
                # Since --port was NOT specified (only --portability),
                # main should override port to 8766!
                assert mock_args.port == 8766
