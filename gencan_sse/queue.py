"""Message queue and playback worker for gencan-sse.

Bridges synchronous callers to the async TTS pipeline. The
:class:`MessageQueue` provides a thread-safe submission interface while the
:class:`PlaybackWorker` drains the queue in a background thread running its
own asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from gencan_sse.chunker import chunk_sentences
from gencan_sse.types import (
    AudioChunk,
    AudioTask,
    EventType,
    Priority,
    SpeakResult,
    VoiceMapping,
)

if TYPE_CHECKING:
    from gencan_sse.providers.base import TTSProvider
    from gencan_sse.audio_player import AudioPlayer
    from gencan_sse.filters import TextFilter
    from gencan_sse.voice_router import VoiceRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Queue message types
# ---------------------------------------------------------------------------

@dataclass
class SpeakMessage:
    """A request to speak text, submitted to the message queue."""
    text: str
    voice: str = "Kore"
    style: str = ""
    priority: Priority = Priority.RESPONSE
    event_type: EventType = EventType.MESSAGE
    timestamp: float = field(default_factory=time.time)
    client_ip: Optional[str] = None


@dataclass
class EventMessage:
    """A structured event to process through the full pipeline."""
    event_json: str
    timestamp: float = field(default_factory=time.time)
    client_ip: Optional[str] = None


@dataclass
class ControlMessage:
    """A control message (stop, flush, volume change, etc.)."""
    action: str  # "stop", "flush", "set_volume", "set_speed", "set_voice"
    payload: dict = field(default_factory=dict)


# Union of all message types
QueueMessage = SpeakMessage | EventMessage | ControlMessage

# Sentinel to signal the worker thread to shut down
_SHUTDOWN = object()


# ---------------------------------------------------------------------------
# PlaybackWorker — runs in a background thread with its own event loop
# ---------------------------------------------------------------------------

class PlaybackWorker:
    """Async worker that processes messages from a thread-safe queue.

    Runs its own asyncio event loop in a dedicated daemon thread. Callers
    submit :class:`SpeakMessage`, :class:`EventMessage`, or
    :class:`ControlMessage` objects via :meth:`submit` (thread-safe).

    Args:
        tts_provider: The TTS backend to use for synthesis.
        audio_player: The audio player for local playback.
        text_filter: Content filter for cleaning text.
        voice_map: Mapping from EventType to (voice_name, style, enabled).
        code_block_chime: Whether to play a chime for code blocks.
    """

    def __init__(
        self,
        tts_provider: TTSProvider,
        audio_player: AudioPlayer,
        text_filter: TextFilter,
        voice_map: dict[EventType, tuple[str, str, bool]],
        voice_router: 'Optional[VoiceRouter]' = None,
        code_block_chime: bool = True,
        min_sentence_length: int = 5,
        target_chunk_size: int = 250,
        on_metrics_callback=None,
    ) -> None:
        self._tts = tts_provider
        self._player = audio_player
        self._filter = text_filter
        self._voice_map = voice_map
        self._voice_router = voice_router
        self._code_block_chime = code_block_chime
        self._min_sentence_length = min_sentence_length
        self._target_chunk_size = target_chunk_size
        self._on_metrics = on_metrics_callback

        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._play_task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        """Whether the worker thread is alive."""
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def queue_depth(self) -> int:
        """Number of messages waiting in the queue."""
        return self._queue.qsize()

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            logger.debug("PlaybackWorker already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="gencan-sse-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("PlaybackWorker started (thread=%s)", self._thread.name)

    def stop(self) -> None:
        """Signal the worker to shut down and wait for it to finish."""
        if not self._running:
            return

        logger.info("PlaybackWorker stopping...")
        self._running = False
        self._queue.put(_SHUTDOWN)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("PlaybackWorker thread did not stop in time")

        logger.info("PlaybackWorker stopped")

    def submit(self, message: QueueMessage) -> int:
        """Submit a message to the queue (thread-safe).

        Args:
            message: The message to enqueue.

        Returns:
            Approximate queue depth after submission.
        """
        self._queue.put(message)
        depth = self._queue.qsize()
        logger.debug(
            "Message submitted: type=%s, queue_depth≈%d",
            type(message).__name__,
            depth,
        )
        return depth

    # -----------------------------------------------------------------------
    # Internal: background thread event loop
    # -----------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Entry point for the background thread — creates and runs the async loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception:
            logger.exception("PlaybackWorker loop crashed")
        finally:
            self._loop.close()
            self._loop = None
            logger.debug("PlaybackWorker event loop closed")

    async def _async_main(self) -> None:
        """Main async loop: start the audio player, then drain the queue."""
        # Start audio playback loop
        self._play_task = asyncio.create_task(self._player.play_loop())

        try:
            while self._running:
                # Get next message (blocking with timeout so we can check _running)
                try:
                    msg = await asyncio.to_thread(self._queue.get, timeout=0.5)
                except Exception:
                    # queue.Empty or timeout
                    continue

                if msg is _SHUTDOWN:
                    logger.debug("Received shutdown sentinel")
                    break

                try:
                    await self._handle_message(msg)
                except Exception:
                    logger.exception("Error handling message: %s", type(msg).__name__)
        finally:
            # Clean up
            await self._player.stop()
            if self._play_task and not self._play_task.done():
                self._play_task.cancel()

    async def _handle_message(self, msg: QueueMessage) -> None:
        """Route a message to the appropriate handler."""
        if isinstance(msg, SpeakMessage):
            await self._handle_speak(msg)
        elif isinstance(msg, EventMessage):
            await self._handle_event(msg)
        elif isinstance(msg, ControlMessage):
            await self._handle_control(msg)
        else:
            logger.warning("Unknown message type: %s", type(msg))

    async def _handle_speak(self, msg: SpeakMessage) -> None:
        """Handle a direct speak request."""
        if not msg.text or not msg.text.strip():
            return

        if self._voice_router and msg.client_ip:
            msg.voice = self._voice_router.get_voice_for_ip(msg.client_ip)

        chunks = chunk_sentences(msg.text, min_length=self._min_sentence_length, target_chunk_size=self._target_chunk_size)
        for chunk in chunks:
            async def _synthesize(text=chunk) -> Optional[bytes]:
                t0 = time.time()
                pcm, metadata = await self._tts.synthesize(text, msg.voice, msg.style)
                latency = time.time() - t0
                if self._on_metrics and metadata:
                    self._on_metrics(metadata)
                elif self._on_metrics:
                    self._on_metrics({"latency_ms": latency * 1000, "audio_bytes": len(pcm) if pcm else 0})

                if not pcm:
                    logger.warning("TTS returned empty response for speak request")
                    from gencan_sse.audio_player import generate_noise
                    pcm = generate_noise(
                        duration_ms=400,
                        sample_rate=self._player._sample_rate,
                        volume=0.15,
                    )
                return pcm

            task = AudioTask(
                task=asyncio.create_task(_synthesize()),
                priority=msg.priority,
                event_type=msg.event_type,
                timestamp=msg.timestamp,
            )
            await self._player.enqueue(task)

        logger.debug(
            "Speak request chunked into %d parts: voice=%s, priority=%s",
            len(chunks), msg.voice, msg.priority.name,
        )

    async def _handle_event(self, msg: EventMessage) -> None:
        """Handle a structured event through the full pipeline."""
        from gencan_sse.classifier import classify
        from gencan_sse.filters import is_code_block

        event = classify(msg.event_json)

        if event.event_type == EventType.SKIP:
            return

        voice_name, style_prefix, enabled = self._voice_map.get(
            event.event_type, ("Kore", "", True)
        )

        if not enabled:
            return

        if self._voice_router and msg.client_ip:
            voice_name = self._voice_router.get_voice_for_ip(msg.client_ip)

        # Code block chime
        if is_code_block(event.text) and self._code_block_chime:
            await self._player.enqueue_chime()

        filtered = self._filter.filter(event.text)
        if not filtered:
            return

        chunks = chunk_sentences(filtered, min_length=self._min_sentence_length, target_chunk_size=self._target_chunk_size)
        for chunk in chunks:
            async def _synthesize(text=chunk) -> Optional[bytes]:
                t0 = time.time()
                pcm, metadata = await self._tts.synthesize(text, voice_name, style_prefix)
                latency = time.time() - t0
                if self._on_metrics and metadata:
                    self._on_metrics(metadata)
                elif self._on_metrics:
                    self._on_metrics({"latency_ms": latency * 1000, "audio_bytes": len(pcm) if pcm else 0})

                if not pcm:
                    from gencan_sse.audio_player import generate_noise
                    pcm = generate_noise(
                        duration_ms=400,
                        sample_rate=self._player._sample_rate,
                        volume=0.15,
                    )
                return pcm

            task = AudioTask(
                task=asyncio.create_task(_synthesize()),
                priority=event.priority,
                event_type=event.event_type,
                timestamp=msg.timestamp,
            )
            await self._player.enqueue(task)

    async def _handle_control(self, msg: ControlMessage) -> None:
        """Handle a control message."""
        action = msg.action

        if action == "set_volume":
            volume = float(msg.payload.get("volume", 0.8))
            self._player._volume = max(0.0, min(1.0, volume))
            logger.debug("Volume set to %.2f", self._player._volume)

        elif action == "set_speed":
            speed = float(msg.payload.get("speed", 1.0))
            self._player.set_speed(speed)
            logger.debug("Speed set to %.2f", speed)

        elif action == "set_voice":
            event_type_str = msg.payload.get("event_type", "")
            voice_name = msg.payload.get("voice_name", "")
            try:
                etype = EventType(event_type_str.lower())
                if etype in self._voice_map:
                    _, style, enabled = self._voice_map[etype]
                    self._voice_map[etype] = (voice_name, style, enabled)
                else:
                    self._voice_map[etype] = (voice_name, "", True)
                logger.debug("Voice for %s set to %s", etype.name, voice_name)
            except ValueError:
                logger.warning("Unknown event type for set_voice: %s", event_type_str)

        elif action == "flush":
            event_type_str = msg.payload.get("event_type", "")
            if event_type_str:
                try:
                    etype = EventType(event_type_str.lower())
                    await self._player.flush_event_type(etype)
                except ValueError:
                    pass
            else:
                async with self._player._lock:
                    self._player._heap.clear()
            logger.debug("Queue flushed (event_type=%s)", event_type_str or "all")

        elif action == "stop":
            async with self._player._lock:
                self._player._heap.clear()
            logger.debug("Queue cleared via stop control")

        elif action == "set_provider":
            new_provider = msg.payload.get("provider")
            if new_provider:
                self._tts = new_provider
                logger.info("TTS provider switched to %s", new_provider.name)

        else:
            logger.warning("Unknown control action: %s", action)
