import array
import asyncio
import heapq
import logging
import math
import struct
import threading
import time
from typing import Optional

try:
    import numpy as np
except ImportError:
    np = None

try:
    import audioop
except ImportError:
    audioop = None

from gencan_sse.types import (
    AudioChunk,
    AudioTask,
    EventType,
    Priority,
)

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
    if np is not None:
        t = np.arange(num_samples) / sample_rate
        # Vectorized fade-in/fade-out envelope
        fade_samples = int(num_samples * 0.1)
        envelope = np.ones(num_samples, dtype=np.float32)
        if fade_samples > 0:
            envelope[:fade_samples] = np.arange(fade_samples) / fade_samples
            envelope[-fade_samples:] = np.arange(fade_samples, 0, -1) / fade_samples
        samples_np = 32767.0 * volume * envelope * np.sin(2.0 * np.pi * frequency * t)
        samples_np = np.clip(samples_np, -32768, 32767).astype(np.int16)
        return samples_np.tobytes()

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
    return array.array('h', samples).tobytes()


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
    return array.array('h', samples).tobytes()


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

    if audioop is not None:
        try:
            return audioop.mul(pcm_data, 2, volume)
        except Exception:
            pass

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
    out_samples = [samples[max(0, min(num_samples_in - 1, int(i * step)))] for i in range(num_samples_out)]
    return struct.pack(f"<{num_samples_out}h", *out_samples)


def _safe_put(q: asyncio.Queue[bytes], data: bytes) -> None:
    try:
        q.put_nowait(data)
    except asyncio.QueueFull:
        pass


class _PriorityEntry:
    """Wrapper for heap queue ordering."""

    def __init__(self, audio_task: AudioTask, counter: int):
        self.priority = audio_task.priority.value
        self.counter = counter
        self.audio_task = audio_task

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
        self._entry_counter = 0
        self._notify: Optional[asyncio.Event] = None
        self._lock: Optional[asyncio.Lock] = None

        self._pyaudio = None
        self._stream = None
        self._running = False
        self._last_event_type: Optional[EventType] = None
        self._write_task: Optional[asyncio.Task] = None
        self._using_desired_device = False
        self._last_init_attempt_time = 0.0
        
        # Audio stream pub/sub
        self._subscribers: set[tuple[asyncio.Queue[bytes], asyncio.AbstractEventLoop]] = set()
        self._subscribers_lock = threading.Lock()

        # Pre-generate chime
        self._chime_pcm = generate_chime(
            frequency=440.0,
            duration_ms=200,
            sample_rate=sample_rate,
            volume=0.3,
        )

        self._init_pyaudio(output_device)

    def init_async_primitives(self) -> None:
        """Initialize asyncio primitives (Event and Lock) on the current event loop."""
        if self._notify is None:
            self._notify = asyncio.Event()
        if self._lock is None:
            self._lock = asyncio.Lock()

    def _cleanup_pyaudio_sync(self) -> None:
        """Synchronously clean up existing stream and PyAudio instances."""
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                logger.debug("Error closing stream in cleanup: %s", e)
            self._stream = None

        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception as e:
                logger.debug("Error terminating PyAudio in cleanup: %s", e)
            self._pyaudio = None

    def _init_pyaudio(self, device_name: Optional[str]) -> None:
        """Initialize PyAudio with optional device selection."""
        logger.debug("_init_pyaudio: device_name=%r", device_name)
        self._last_init_attempt_time = time.time()
        self._cleanup_pyaudio_sync()
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
                    self._using_desired_device = False
                else:
                    self._using_desired_device = True
            else:
                self._using_desired_device = True

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
            self._using_desired_device = False
        except Exception as e:
            logger.warning("Failed to initialize audio: %s. Silent mode.", e)
            logger.debug("_init_pyaudio: exception details", exc_info=True)
            self._using_desired_device = False

    async def enqueue(self, audio_task: AudioTask) -> None:
        """Add an AudioTask to the priority queue. Non-blocking."""
        if self._lock is None:
            self.init_async_primitives()
        async with self._lock:
            # Evict stale entries
            now = time.time()
            stale_entries = []
            fresh_entries = []
            for e in self._heap:
                if (now - e.audio_task.timestamp) >= self._stale_timeout and e.audio_task.priority != Priority.ERROR:
                    stale_entries.append(e)
                else:
                    fresh_entries.append(e)
            
            for e in stale_entries:
                if not e.audio_task.task.done():
                    e.audio_task.task.cancel()

            self._entry_counter += 1
            new_entry = _PriorityEntry(audio_task, self._entry_counter)
            candidates = fresh_entries + [new_entry]

            # Enforce max depth — drop oldest/lowest priority non-error entries
            drop_count = len(candidates) - self._max_depth
            if drop_count > 0:
                non_errors = [e for e in candidates if e.audio_task.priority != Priority.ERROR]
                # sort so that lowest priority (largest value -> smallest negative) and oldest (smallest counter) are first
                non_errors.sort(key=lambda e: (-e.priority, e.counter))
                to_drop_count = min(drop_count, len(non_errors))
                evicted = non_errors[:to_drop_count]
                for e in evicted:
                    if not e.audio_task.task.done():
                        e.audio_task.task.cancel()
                    logger.debug("Evicted stale/low-priority entry from queue")
                survivors = [e for e in candidates if e.audio_task.priority == Priority.ERROR] + non_errors[to_drop_count:]
            else:
                survivors = candidates

            # Atomic assignment to self._heap
            new_heap = list(survivors)
            heapq.heapify(new_heap)
            self._heap = new_heap

        self._notify.set()
        logger.debug("Enqueued AudioTask: priority=%s, queue_depth=%d",
                      audio_task.priority.name, len(self._heap))

    async def enqueue_chime(self) -> None:
        """Enqueue a code-block chime tone."""
        async def _chime_pcm() -> bytes:
            return self._chime_pcm

        task = AudioTask(
            task=asyncio.create_task(_chime_pcm()),
            priority=Priority.TOOL,
            event_type=EventType.SKIP,
        )
        await self.enqueue(task)

    async def enqueue_error_chime(self) -> None:
        """Enqueue a low-pitch error tone."""
        async def _chime_pcm() -> bytes:
            return generate_chime(
                frequency=150.0,
                duration_ms=300,
                sample_rate=self._sample_rate,
                volume=0.4,
            )

        task = AudioTask(
            task=asyncio.create_task(_chime_pcm()),
            priority=Priority.ERROR,
            event_type=EventType.ERROR,
        )
        await self.enqueue(task)

    async def flush_event_type(self, old_type: EventType) -> None:
        """Flush queued entries of a specific event type on transition."""
        if self._lock is None:
            self.init_async_primitives()
        async with self._lock:
            surviving = []
            for e in self._heap:
                if e.audio_task.event_type == old_type and e.audio_task.priority != Priority.ERROR:
                    if not e.audio_task.task.done():
                        e.audio_task.task.cancel()
                else:
                    surviving.append(e)
            self._heap = surviving
            heapq.heapify(self._heap)
        logger.debug("Flushed stale entries for event type: %s", old_type.name)

    async def play_loop(self) -> None:
        """Continuously play from priority queue. Run as background task."""
        self.init_async_primitives()
        self._running = True
        logger.info("Audio playback loop started (priority mode)")
        logger.debug("play_loop: has_stream=%s, volume=%.2f, max_depth=%d, stale_timeout=%.1f",
                     self._stream is not None, self._volume, self._max_depth, self._stale_timeout)

        current_entry = None
        while self._running:
            if current_entry is None:
                # Acquire lock and try to pop atomically to avoid TOCTOU race
                async with self._lock:
                    if self._heap:
                        current_entry = heapq.heappop(self._heap)
                    else:
                        current_entry = None

            if current_entry is None:
                # Heap was empty — wait for notification without holding lock
                notify_task = asyncio.create_task(self._notify.wait())
                try:
                    await asyncio.wait_for(notify_task, timeout=0.5)
                    # Notified
                    self._notify.clear()
                except asyncio.TimeoutError:
                    pass
                finally:
                    if not notify_task.done():
                        notify_task.cancel()
                        try:
                            await notify_task
                        except asyncio.CancelledError:
                            pass
                continue

            audio_task = current_entry.audio_task
            age = time.time() - audio_task.timestamp

            if age > self._stale_timeout and audio_task.priority != Priority.ERROR:
                if not audio_task.task.done():
                    audio_task.task.cancel()
                current_entry = None
                continue

            # Await synthesis with preemption
            preempted = False
            while not audio_task.task.done() and self._running:
                notify_task = asyncio.create_task(self._notify.wait())
                try:
                    done, pending = await asyncio.wait(
                        [audio_task.task, notify_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    if notify_task in done:
                        if not self._running:
                            break
                        # A new item was enqueued. Re-evaluate priorities.
                        # Only preempt and push current_entry back to the heap if the new item is indeed higher priority.
                        async with self._lock:
                            if self._heap and self._heap[0] < current_entry:
                                heapq.heappush(self._heap, current_entry)
                                preempted = True
                                self._notify.clear()
                                break
                            else:
                                self._notify.clear()
                finally:
                    if not notify_task.done():
                        notify_task.cancel()
                        try:
                            await notify_task
                        except asyncio.CancelledError:
                            pass

            if not self._running:
                if not audio_task.task.done():
                    audio_task.task.cancel()
                current_entry = None
                continue

            if preempted:
                current_entry = None
                continue

            # Synthesis completed
            try:
                pcm = audio_task.task.result()
            except asyncio.CancelledError:
                current_entry = None
                continue
            except Exception as e:
                logger.warning("Synthesis task failed: %s", e)
                current_entry = None
                continue

            current_entry = None

            if not pcm:
                continue

            age = time.time() - audio_task.timestamp
            if age > self._stale_timeout and audio_task.priority != Priority.ERROR:
                logger.debug("Dropped stale audio after synthesis (age=%.1fs, type=%s)", age, audio_task.event_type.name)
                continue

            # Apply volume
            if self._volume < 1.0:
                pcm = await asyncio.to_thread(apply_volume, pcm, self._volume)

            # Play
            try:
                now = time.time()
                if (self._stream is None or not self._using_desired_device) and (now - self._last_init_attempt_time >= 5.0):
                    logger.info("Attempting to re-initialize audio player (desired device: %s)...", self._output_device)
                    await asyncio.to_thread(self._init_pyaudio, self._output_device)

                target_rate = int(self._sample_rate * self._speed)
                resampled_pcm = await asyncio.to_thread(resample_pcm, pcm, target_rate, self._hardware_rate)
                duration_est = len(resampled_pcm) / (self._hardware_rate * self._sample_width * self._channels)

                # Broadcast to network subscribers
                with self._subscribers_lock:
                    subscribers_snapshot = list(self._subscribers)
                
                for q, loop in subscribers_snapshot:
                    try:
                        loop.call_soon_threadsafe(_safe_put, q, resampled_pcm)
                    except Exception as e:
                        logger.debug("Failed to broadcast chunk to subscriber: %s", e)

                if self._stream:
                    play_t0 = time.time()
                    self._write_task = asyncio.create_task(asyncio.to_thread(self._stream.write, resampled_pcm))
                    try:
                        await self._write_task
                    finally:
                        self._write_task = None
                    play_elapsed = time.time() - play_t0
                    logger.debug("Played %d bytes in %.3fs (priority=%s, type=%s, age=%.1fs, remaining=%d)",
                                 len(pcm), play_elapsed, audio_task.priority.name,
                                 audio_task.event_type.name, age, len(self._heap))
                else:
                    logger.debug("Silent mode: skipped %d bytes (~%.1fs audio)", len(pcm), duration_est)
            except Exception as e:
                logger.warning("Error writing to audio stream: %s. Releasing audio player...", e)
                await asyncio.to_thread(self._cleanup_pyaudio_sync)
                self._using_desired_device = False

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def queue_depth(self) -> int:
        return len(self._heap)

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue[bytes]:
        """Subscribe to the audio stream. Returns an asyncio.Queue of PCM bytes."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        q = asyncio.Queue(maxsize=maxsize)
        with self._subscribers_lock:
            self._subscribers.add((q, loop))
        return q
        
    def unsubscribe(self, q: asyncio.Queue[bytes]) -> None:
        """Unsubscribe from the audio stream."""
        with self._subscribers_lock:
            to_remove = [item for item in self._subscribers if item[0] is q]
            for item in to_remove:
                self._subscribers.discard(item)

    def set_speed(self, speed: float) -> None:
        """Update playback speed dynamically."""
        speed = max(0.5, min(2.0, speed))
        if self._speed == speed:
            return

        logger.info("Changing playback speed from %.2fx to %.2fx", self._speed, speed)
        self._speed = speed

    def set_volume(self, volume: float) -> None:
        """Update playback volume dynamically."""
        self._volume = max(0.0, min(1.0, volume))
        logger.info("Volume set to %.0f%%", self._volume * 100)

    async def clear_queue(self) -> None:
        """Cancel all pending audio tasks and clear the queue."""
        if self._lock is None:
            self.init_async_primitives()
        async with self._lock:
            for entry in self._heap:
                if not entry.audio_task.task.done():
                    entry.audio_task.task.cancel()
            self._heap.clear()
        logger.debug("Audio queue cleared")

    async def stop(self) -> None:
        """Stop playback and clean up resources."""
        logger.debug("AudioPlayer.stop: stopping (queue_depth=%d, running=%s)", len(self._heap), self._running)
        self._running = False
        if self._notify is not None:
            self._notify.set()  # Unblock the loop

        if self._lock is None:
            self.init_async_primitives()

        async with self._lock:
            for entry in self._heap:
                if not entry.audio_task.task.done():
                    entry.audio_task.task.cancel()
            self._heap.clear()

        if self._write_task and not self._write_task.done():
            try:
                logger.debug("AudioPlayer.stop: awaiting active write task")
                await self._write_task
                logger.debug("AudioPlayer.stop: active write task finished")
            except Exception as e:
                logger.warning("Error awaiting write task during stop: %s", e)

        await asyncio.to_thread(self._cleanup_pyaudio_sync)
        logger.info("Audio player stopped")
