import asyncio
import time
from unittest.mock import MagicMock, patch
import pytest

from gencan_sse.audio_player import AudioPlayer
from gencan_sse.types import AudioTask, Priority, EventType


@pytest.mark.asyncio
async def test_device_not_found_fallback():
    """Verify that if the desired device is absent, we fall back to default and track status."""
    mock_devices = [
        {"name": "Built-in Output", "defaultSampleRate": 44100},
    ]

    with patch("pyaudio.PyAudio") as mock_pa_cls:
        mock_pa = MagicMock()
        mock_pa_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = len(mock_devices)
        mock_pa.get_device_info_by_index.side_effect = lambda idx: mock_devices[idx]
        mock_pa.get_default_output_device_info.return_value = mock_devices[0]

        player = AudioPlayer(output_device="Sabre DAC", reconnect_retries=1, reconnect_delay=0.0)
        
        # Should fall back to default because "Sabre DAC" isn't in mock_devices
        assert player._using_desired_device is False
        assert player._stream is not None
        # Verify it opened the default (device_index=None)
        mock_pa.open.assert_called_once()
        kwargs = mock_pa.open.call_args[1]
        assert kwargs.get("output_device_index") is None
        await player.stop()


@pytest.mark.asyncio
async def test_reconnect_when_device_becomes_available():
    """Verify that the player dynamically detects and switches to the Sabre DAC when it is reconnected."""
    mock_devices = [
        {"name": "Built-in Output", "defaultSampleRate": 44100},
    ]

    with patch("pyaudio.PyAudio") as mock_pa_cls:
        mock_pa = MagicMock()
        mock_pa_cls.return_value = mock_pa
        mock_pa.get_device_count.side_effect = lambda: len(mock_devices)
        mock_pa.get_device_info_by_index.side_effect = lambda idx: mock_devices[idx]
        mock_pa.get_default_output_device_info.return_value = mock_devices[0]

        player = AudioPlayer(output_device="Sabre DAC", reconnect_retries=1, reconnect_delay=0.0)
        player.init_async_primitives()
        assert player._using_desired_device is False

        # Simulate time passing, and plug in the Sabre DAC
        player._last_init_attempt_time = time.time() - 6.0
        mock_devices.append({"name": "Sabre DAC", "defaultSampleRate": 48000})

        # Run play_loop in the background
        loop_task = asyncio.create_task(player.play_loop())

        # Enqueue a dummy task to trigger the play check
        fut = asyncio.Future()
        fut.set_result(b"\x00" * 1000)  # some silent PCM
        task = AudioTask(task=fut, priority=Priority.RESPONSE, event_type=EventType.MESSAGE)
        await player.enqueue(task)

        # Allow play_loop to check and re-initialize
        await asyncio.sleep(0.1)

        # It should now be using the Sabre DAC
        assert player._using_desired_device is True
        assert player._hardware_rate == 48000
        
        # Verify it opened stream with device_index = 1
        open_calls = mock_pa.open.call_args_list
        assert len(open_calls) > 1
        last_kwargs = open_calls[-1][1]
        assert last_kwargs.get("output_device_index") == 1

        await player.stop()
        try:
            await loop_task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_pyaudio_cleanup_on_write_failure():
    """Verify that a write exception cleans up PyAudio/stream and flags the device as offline."""
    mock_devices = [
        {"name": "Sabre DAC", "defaultSampleRate": 48000},
    ]

    with patch("pyaudio.PyAudio") as mock_pa_cls:
        mock_pa = MagicMock()
        mock_pa_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = len(mock_devices)
        mock_pa.get_device_info_by_index.side_effect = lambda idx: mock_devices[idx]
        
        mock_stream = MagicMock()
        # Make stream.write raise an OSError (representing unplugging mid-play)
        mock_stream.write.side_effect = OSError("Device disconnected")
        mock_pa.open.return_value = mock_stream

        player = AudioPlayer(output_device="Sabre DAC", reconnect_retries=1, reconnect_delay=0.0)
        player.init_async_primitives()
        assert player._using_desired_device is True

        # Run play_loop in background
        loop_task = asyncio.create_task(player.play_loop())

        # Enqueue dummy task
        fut = asyncio.Future()
        fut.set_result(b"\x00" * 1000)
        task = AudioTask(fut, priority=Priority.RESPONSE, event_type=EventType.MESSAGE)
        await player.enqueue(task)

        # Allow time to fail write and run error handling
        await asyncio.sleep(0.1)

        # Verify stream is cleaned up and state is offline
        assert player._stream is None
        assert player._pyaudio is None
        assert player._using_desired_device is False
        mock_stream.close.assert_called()

        await player.stop()
        try:
            await loop_task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_audio_player_idle_cleanup():
    """Verify that the player closes the stream and sets the idle cleanup flag when idle."""
    mock_devices = [
        {"name": "Sabre DAC", "defaultSampleRate": 48000},
    ]

    with patch("pyaudio.PyAudio") as mock_pa_cls:
        mock_pa = MagicMock()
        mock_pa_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = len(mock_devices)
        mock_pa.get_device_info_by_index.side_effect = lambda idx: mock_devices[idx]

        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream

        # Instantiate with a short idle timeout (0.1 seconds)
        player = AudioPlayer(
            output_device="Sabre DAC",
            idle_timeout=0.1,
            reconnect_retries=1,
            reconnect_delay=0.0
        )
        player.init_async_primitives()
        assert player._stream is not None
        assert player._idle_cleaned_up is False

        # Run play_loop in background
        loop_task = asyncio.create_task(player.play_loop())

        # Wait for the idle timeout to trigger (should take >0.1 seconds)
        await asyncio.sleep(0.25)

        # Verify it cleaned up the stream and set the flag
        assert player._stream is None
        assert player._pyaudio is None
        assert player._idle_cleaned_up is True
        mock_stream.close.assert_called_once()

        await player.stop()
        try:
            await loop_task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_audio_player_retry_logic():
    """Verify that PyAudio initialization retries multiple times when the desired device is initially missing."""
    mock_devices_empty = [
        {"name": "Built-in Output", "defaultSampleRate": 44100},
    ]
    mock_devices_with_dac = [
        {"name": "Built-in Output", "defaultSampleRate": 44100},
        {"name": "Sabre DAC", "defaultSampleRate": 48000},
    ]

    # Keep track of calls to PyAudio constructor/device scanning
    pyaudio_instantiations = 0

    def mock_pyaudio_side_effect():
        nonlocal pyaudio_instantiations
        pyaudio_instantiations += 1
        mock_pa = MagicMock()
        if pyaudio_instantiations < 3:
            # First two calls: device is missing
            devices = mock_devices_empty
        else:
            # Third call: device is present
            devices = mock_devices_with_dac
            
        mock_pa.get_device_count.return_value = len(devices)
        mock_pa.get_device_info_by_index.side_effect = lambda idx: devices[idx]
        mock_pa.get_default_output_device_info.return_value = devices[0]
        return mock_pa

    with patch("pyaudio.PyAudio", side_effect=mock_pyaudio_side_effect):
        # We start with device missing, expect 3 retries (0.01s delay)
        # On attempt 3 it should succeed
        player = AudioPlayer(
            output_device="Sabre DAC",
            reconnect_retries=3,
            reconnect_delay=0.01
        )
        
        assert player._using_desired_device is True
        assert pyaudio_instantiations == 3
        assert player._stream is not None
        await player.stop()

