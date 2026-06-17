"""Audio Player module — async PCM playback with priority queue."""

import asyncio
import heapq
import logging
import math
import struct
import time
from typing import Optional

from gencan_sse.types import AudioChunk, Priority, EventType

logger = logging.getLogger(__name__)


def generate_chime(
    frequency: float = 440.0,
    duration_ms: int = 200,
    sample_rate: int = 24000,
    volume: float = 0.3,
) -> bytes:
    """Generate a short sine-wave chime as PCM audio.

    Args:
        frequency: Tone frequency in Hz.
        duration_ms: Duration in milliseconds.
        sample_rate: Audio sample rate in Hz.
        volume: Volume level (0.0 to 1.0).

    Returns:
        Raw PCM bytes (16-bit signed, mono).
    """
    num_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        # Apply fade-in/fade-out envelope
        envelope = 1.0
        fade_samples = int(num_samples * 0.1)
        if i < fade_samples:
            envelope = i / fade_samples
        elif i > num_samples - fade_samples:
            envelope = (num_samples - i) / fade_samples
        sample = int(32767 * volume * envelope * math.sin(2.0 * math.pi * frequency * t))
        samples.append(max(-32768, min(32767, sample)))
    return struct.pack(f"<{len(samples)}h", *samples)


def generate_noise(
    duration_ms: int = 300,
    sample_rate: int = 24000,
    volume: float = 0.15,
) -> bytes:
    """Generate a short burst of white noise (static) as PCM audio.

    Args:
        duration_ms: Duration in milliseconds.
        sample_rate: Audio sample rate in Hz.
        volume: Volume level (0.0 to 1.0).

    Returns:
        Raw PCM bytes (16-bit signed, mono).
    """
    import random
    num_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for _ in range(num_samples):
        val = random.uniform(-1.0, 1.0)
        sample = int(32767 * volume * val)
        samples.append(max(-32768, min(32767, sample)))
    return struct.pack(f"<{len(samples)}h", *samples)


def apply_volume(pcm_data: bytes, volume: float) -> bytes:
    """Apply volume gain to PCM audio data.

    Args:
        pcm_data: Raw PCM bytes (16-bit signed, mono).
        volume: Volume multiplier (0.0 to 1.0).

    Returns:
        Volume-adjusted PCM bytes.
    """
    if volume >= 1.0 or not pcm_data:
        return pcm_data
    if volume <= 0.0:
        return b"\x00" * len(pcm_data)

    num_samples = len(pcm_data) // 2
    samples = struct.unpack(f"<{num_samples}h", pcm_data[:num_samples * 2])
    adjusted = [max(-32768, min(32767, int(s * volume))) for s in samples]
    return struct.pack(f"<{len(adjusted)}h", *adjusted)


def resample_pcm(pcm_data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample mono 16-bit PCM using nearest-neighbor interpolation."""
    if from_rate == to_rate or not pcm_data:
        return pcm_data
    
    num_samples_in = len(pcm_data) // 2
    if num_samples_in == 0:
        return b""
        
    samples = struct.unpack(f"<{num_samples_in}h", pcm_data)
    num_samples_out = int(num_samples_in * to_rate / from_rate)
    
    step = from_rate / to_rate
    out_samples = [samples[int(i * step)] for i in range(num_samples_out)]
    return struct.pack(f"<{num_samples_out}h", *out_samples)


class _PriorityEntry:
    """Wrapper for heap queue ordering."""
    _counter = 0

    def __init__(self, chunk: AudioChunk):
        _PriorityEntry._counter += 1
        self.priority = chunk.priority.value
        self.counter = _PriorityEntry._counter
        self.chunk = chunk

    def __lt__(self, other):
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.counter < other.counter


class AudioPlayer:
    """Async audio playback with priority queue and queue management.

    Features:
    - Priority-ordered playback (errors jump ahead)
    - Max queue depth with oldest-entry eviction
    - Stale entry timeout
    - Volume control
    - Output device selection
    - Code block chime support
    """

    def __init__(
        self,
        sample_rate: int = 24000,
        sample_width: int = 2,
        channels: int = 1,
        volume: float = 0.8,
        speed: float = 1.0,
        max_queue_depth: int = 5,
        stale_timeout: float = 10.0,
        output_device: Optional[str] = None,
    ):
        """Initialize the audio player.

        Args:
            sample_rate: Audio sample rate in Hz.
            sample_width: Bytes per sample (2 = 16-bit).
            channels: Number of audio channels (1 = mono).
            volume: Playback volume (0.0 to 1.0).
            speed: Playback speed multiplier (0.5 to 2.0).
            max_queue_depth: Maximum entries in the queue.
            stale_timeout: Seconds before a queued entry is dropped.
            output_device: PyAudio device name (None = system default).
        """
        self._sample_rate = sample_rate
        self._sample_width = sample_width
        self._channels = channels
        self._volume = max(0.0, min(1.0, volume))
        self._speed = max(0.5, min(2.0, speed))
        self._max_depth = max_queue_depth
        self._stale_timeout = stale_timeout
        self._output_device = output_device
        self._hardware_rate = sample_rate

        # Priority heap + async notification
        self._heap: list[_PriorityEntry] = []
        self._notify = asyncio.Event()
        self._lock = asyncio.Lock()

        self._pyaudio = None
        self._stream = None
        self._running = False
        self._last_event_type: Optional[EventType] = None

        # Pre-generate chime
        self._chime_pcm = generate_chime(
            frequency=440.0,
            duration_ms=200,
            sample_rate=sample_rate,
            volume=0.3,
        )

        self._init_pyaudio(output_device)

    def _init_pyaudio(self, device_name: Optional[str]) -> None:
        """Initialize PyAudio with optional device selection."""
        logger.debug("_init_pyaudio: device_name=%r", device_name)
        try:
            import pyaudio
            self._pyaudio = pyaudio.PyAudio()
            logger.debug("_init_pyaudio: PyAudio created, device_count=%d", self._pyaudio.get_device_count())

            device_index = None
            if device_name:
                for i in range(self._pyaudio.get_device_count()):
                    info = self._pyaudio.get_device_info_by_index(i)
                    logger.debug("_init_pyaudio: device[%d] = %s (max_out=%s)",
                                 i, info["name"], info.get("maxOutputChannels", "?"))
                    if device_name.lower() in info["name"].lower():
                        device_index = i
                        logger.info("Using audio device: %s (index %d)", info["name"], i)
                        break
                if device_index is None:
                    logger.warning("Device '%s' not found. Using default.", device_name)

            if device_index is not None:
                device_info = self._pyaudio.get_device_info_by_index(device_index)
            else:
                device_info = self._pyaudio.get_default_output_device_info()

            self._hardware_rate = int(device_info.get("defaultSampleRate", 48000))
            logger.info("Output device native sample rate: %d Hz", self._hardware_rate)

            self._stream = self._pyaudio.open(
                format=self._pyaudio.get_format_from_width(self._sample_width),
                channels=self._channels,
                rate=self._hardware_rate,
                output=True,
                output_device_index=device_index,
                frames_per_buffer=2048,
            )
            logger.info("Audio player initialized: %dHz hardware stream (resampling from %dHz at %.2fx speed), %d-bit, vol=%.0f%%",
                        self._hardware_rate, self._sample_rate, self._speed,
                        self._sample_width * 8, self._volume * 100)
            logger.debug("_init_pyaudio: stream opened successfully, device_index=%s", device_index)
        except ImportError:
            logger.warning("PyAudio not installed. Running in silent mode.")
        except Exception as e:
            logger.warning("Failed to initialize audio: %s. Silent mode.", e)
            logger.debug("_init_pyaudio: exception details", exc_info=True)

    async def enqueue(self, chunk: AudioChunk) -> None:
        """Add audio to the priority queue. Non-blocking."""
        async with self._lock:
            # Evict stale entries
            now = time.time()
            self._heap = [
                e for e in self._heap
                if (now - e.chunk.timestamp) < self._stale_timeout
                or e.chunk.priority == Priority.ERROR
            ]

            # Enforce max depth — drop oldest non-error entries
            while len(self._heap) >= self._max_depth:
                # Find lowest-priority (highest .value) non-error entry
                non_errors = [e for e in self._heap if e.chunk.priority != Priority.ERROR]
                if non_errors:
                    victim = max(non_errors, key=lambda e: (e.priority, -e.counter))
                    self._heap.remove(victim)
                    logger.debug("Evicted stale/low-priority entry from queue")
                else:
                    break  # All errors, don't drop

            heapq.heappush(self._heap, _PriorityEntry(chunk))
            heapq.heapify(self._heap)  # Re-sort after stale eviction

        self._notify.set()
        logger.debug("Enqueued: %d bytes, priority=%s, queue_depth=%d",
                      len(chunk.pcm_data), chunk.priority.name, len(self._heap))

    async def enqueue_chime(self) -> None:
        """Enqueue a code-block chime tone."""
        chunk = AudioChunk(
            pcm_data=self._chime_pcm,
            priority=Priority.TOOL,
            event_type=EventType.SKIP,
        )
        await self.enqueue(chunk)

    async def flush_event_type(self, old_type: EventType) -> None:
        """Flush queued entries of a specific event type on transition."""
        async with self._lock:
            self._heap = [
                e for e in self._heap
                if e.chunk.event_type != old_type
                or e.chunk.priority == Priority.ERROR
            ]
            heapq.heapify(self._heap)
        logger.debug("Flushed stale entries for event type: %s", old_type.name)

    async def play_loop(self) -> None:
        """Continuously play from priority queue. Run as background task."""
        self._running = True
        logger.info("Audio playback loop started (priority mode)")
        logger.debug("play_loop: has_stream=%s, volume=%.2f, max_depth=%d, stale_timeout=%.1f",
                     self._stream is not None, self._volume, self._max_depth, self._stale_timeout)

        while self._running:
            # Wait for notification or timeout
            try:
                await asyncio.wait_for(self._notify.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            self._notify.clear()
            logger.debug("play_loop: notified, draining queue (depth=%d)", len(self._heap))

            # Drain all available entries in priority order
            while self._running:
                async with self._lock:
                    if not self._heap:
                        break
                    entry = heapq.heappop(self._heap)

                chunk = entry.chunk
                if not chunk.pcm_data:
                    logger.debug("play_loop: skipping chunk with no pcm_data")
                    continue

                # Check staleness
                age = time.time() - chunk.timestamp
                if age > self._stale_timeout:
                    if chunk.priority != Priority.ERROR:
                        logger.debug("Dropped stale audio chunk (age=%.1fs > timeout=%.1fs, type=%s)",
                                     age, self._stale_timeout, chunk.event_type.name)
                        continue
                    else:
                        logger.debug("play_loop: playing stale ERROR chunk (age=%.1fs)", age)

                # Apply volume
                pcm = apply_volume(chunk.pcm_data, self._volume) if self._volume < 1.0 else chunk.pcm_data
                duration_est = len(pcm) / (self._sample_rate * self._sample_width)

                # Play
                try:
                    if self._stream:
                        play_t0 = time.time()
                        target_rate = int(self._sample_rate * self._speed)
                        resampled_pcm = resample_pcm(pcm, target_rate, self._hardware_rate)
                        await asyncio.to_thread(self._stream.write, resampled_pcm)
                        play_elapsed = time.time() - play_t0
                        logger.debug("Played %d bytes (resampled to %d bytes) in %.3fs (priority=%s, type=%s, age=%.1fs, remaining=%d)",
                                     len(pcm), len(resampled_pcm), play_elapsed, chunk.priority.name,
                                     chunk.event_type.name, age, len(self._heap))
                    else:
                        logger.debug("Silent mode: skipped %d bytes (~%.1fs audio)", len(pcm), duration_est)
                except Exception as e:
                    logger.warning("Error writing to audio stream: %s", e)

        logger.info("Audio playback loop stopped")

    def set_speed(self, speed: float) -> None:
        """Update playback speed dynamically."""
        speed = max(0.5, min(2.0, speed))
        if self._speed == speed:
            return

        logger.info("Changing playback speed from %.2fx to %.2fx", self._speed, speed)
        self._speed = speed

    async def stop(self) -> None:
        """Stop playback and clean up resources."""
        logger.debug("AudioPlayer.stop: stopping (queue_depth=%d, running=%s)", len(self._heap), self._running)
        self._running = False
        self._notify.set()  # Unblock the loop

        if self._stream:
            try:
                logger.debug("AudioPlayer.stop: closing audio stream")
                self._stream.stop_stream()
                self._stream.close()
                logger.debug("AudioPlayer.stop: audio stream closed")
            except Exception as e:
                logger.warning("Error closing audio stream: %s", e)

        if self._pyaudio:
            try:
                logger.debug("AudioPlayer.stop: terminating PyAudio")
                self._pyaudio.terminate()
                logger.debug("AudioPlayer.stop: PyAudio terminated")
            except Exception as e:
                logger.warning("Error terminating PyAudio: %s", e)

        logger.info("Audio player stopped")
