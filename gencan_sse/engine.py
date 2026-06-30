"""GenCan Speech Synthesis Engine — main facade.

Provides the :class:`SpeechEngine` class, the primary public interface for
all consumers (MCP servers, screen readers, CLI scripts, etc.).

Usage::

    from gencan_sse import SpeechEngine

    engine = SpeechEngine()
    engine.start()
    engine.speak("Hello, world!")   # synchronous, returns immediately
    engine.speak("Queued next.")    # plays after the first utterance
    engine.stop()                   # graceful shutdown
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Optional, TYPE_CHECKING

from gencan_sse.config import EngineConfig
from gencan_sse.types import (
    EngineStatus,
    EventType,
    Priority,
    SpeakResult,
    VoiceMapping,
)
from gencan_sse.queue import (
    ControlMessage,
    EventMessage,
    PlaybackWorker,
    SpeakMessage,
)
from gencan_sse.filters import TextFilter
from gencan_sse.audio_player import AudioPlayer
from gencan_sse.voice_router import VoiceRouter

if TYPE_CHECKING:
    from gencan_sse.providers.base import TTSProvider

logger = logging.getLogger(__name__)


def _build_voice_map(
    config: EngineConfig,
) -> dict[EventType, tuple[str, str, bool]]:
    """Build a lookup map from EventType to (voice_name, style_prefix, enabled)."""
    type_key_map = {
        EventType.MESSAGE: "message",
        EventType.THINKING: "thinking",
        EventType.TOOL_USE: "tool_use",
        EventType.TOOL_RESULT: "tool_result",
        EventType.ERROR: "error",
    }
    voice_map: dict[EventType, tuple[str, str, bool]] = {}
    for etype, key in type_key_map.items():
        if key in config.voices:
            vc = config.voices[key]
            voice_map[etype] = (vc.voice_name, vc.style_prefix, vc.enabled)
        else:
            voice_map[etype] = (config.default_voice, "", True)
    return voice_map


class SpeechEngine:
    """GenCan Speech Synthesis Engine.

    Synchronous facade over an async TTS pipeline. Callers interact with
    simple blocking methods (``speak``, ``set_volume``, etc.) while the
    engine manages an internal message queue and background playback thread.

    Args:
        config: Engine configuration. Uses sensible defaults if ``None``.
        tts_provider: Custom TTS backend. If ``None``, the default
            :class:`~gencan_sse.providers.gemini.GeminiTTSProvider` is
            created from *config*.

    Example::

        engine = SpeechEngine()
        engine.start()
        engine.speak("Hello!")
        engine.stop()
    """

    def __init__(
        self,
        config: EngineConfig | None = None,
        tts_provider: TTSProvider | None = None,
    ) -> None:
        self._config = config or EngineConfig()
        self._start_time: float = 0.0
        self._is_running = False

        # Build voice routing map
        self._voice_map = _build_voice_map(self._config)

        # Create or accept TTS provider
        if tts_provider is not None:
            self._tts_provider = tts_provider
        else:
            import sys
            
            # Prefer Kokoro on macOS if installed (Disabled to fall back to Gemini)
            # if sys.platform == "darwin":
            #     from gencan_sse.providers.kokoro import KokoroTTSProvider
            #     provider = KokoroTTSProvider()
            #     if provider.is_available:
            #         self._tts_provider = provider

            
            if not hasattr(self, "_tts_provider"):
                from gencan_sse.providers.gemini import GeminiTTSProvider
                self._tts_provider = GeminiTTSProvider(
                    model=self._config.tts_model,
                    fallback_models=self._config.tts_fallback_models,
                    requests_per_minute=self._config.tts_requests_per_minute,
                    round_robin_mode=self._config.tts_round_robin,
                )

        # Create audio player
        self._player = AudioPlayer(
            sample_rate=self._config.sample_rate,
            sample_width=self._config.sample_width,
            channels=self._config.channels,
            volume=self._config.volume,
            speed=self._config.speed,
            max_queue_depth=self._config.max_queue_depth,
            stale_timeout=self._config.stale_timeout_seconds,
            output_device=self._config.output_device,
        )

        # Create text filter
        self._text_filter = TextFilter()

        # Create voice router
        self._voice_router = VoiceRouter(
            voice_pool=self._config.premium_voice_pool,
            timeout_hours=self._config.ip_voice_timeout_hours,
        )

        # Create playback worker (not started yet)
        self._worker = PlaybackWorker(
            tts_provider=self._tts_provider,
            audio_player=self._player,
            text_filter=self._text_filter,
            voice_map=self._voice_map,
            voice_router=self._voice_router,
            code_block_chime=self._config.code_block_chime,
            min_sentence_length=self._config.min_sentence_length,
            target_chunk_size=self._config.target_chunk_size,
            on_metrics_callback=self._record_chunk_metrics,
        )

        # Activity logging and usage tracking
        self._activity_log: list[dict] = []
        self._usage_stats: dict = {
            "total_characters": 0,
            "total_requests": 0,
            "failed_requests": 0,
            "estimated_cost_usd": 0.0,
            "by_model": {},
            "by_provider": {},
            "chunk_metrics": {"total_latency_ms": 0.0, "total_audio_bytes": 0, "total_chunks": 0},
        }

        logger.info(
            "SpeechEngine created: tts_provider=%s, volume=%.2f, speed=%.2f",
            self._tts_provider.name,
            self._config.volume,
            self._config.speed,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the engine.

        Launches the background playback thread. Must be called before
        :meth:`speak` or any other operation.
        """
        if self._is_running:
            logger.debug("Engine already running")
            return

        self._start_time = time.time()
        self._worker.start()
        self._is_running = True
        logger.info("SpeechEngine started")

    def stop(self) -> None:
        """Stop the engine and release all resources.

        Waits for the playback queue to drain (up to the worker's join
        timeout) before returning.
        """
        if not self._is_running:
            return

        self._worker.stop()
        self._is_running = False
        logger.info(
            "SpeechEngine stopped (uptime=%.1fs)",
            time.time() - self._start_time,
        )

    @property
    def is_running(self) -> bool:
        """Whether the engine is currently running."""
        return self._is_running and self._worker.is_running

    # ------------------------------------------------------------------
    # Speaking
    # ------------------------------------------------------------------

    def speak(
        self,
        text: str,
        voice: str | None = None,
        style: str = "",
        priority: Priority = Priority.RESPONSE,
        event_type: EventType = EventType.MESSAGE,
        client_ip: str | None = None,
    ) -> SpeakResult:
        """Speak text aloud.

        Enqueues the text for synthesis and playback. Returns immediately;
        audio plays in the background without blocking.

        Args:
            text: The text to speak.
            voice: Voice name (e.g. ``"Kore"``). Defaults to
                :attr:`EngineConfig.default_voice`.
            style: Style prefix (e.g. ``"[alert] "``).
            priority: Queue priority for this utterance.
            event_type: Event category for voice routing.

        Returns:
            A :class:`SpeakResult` indicating whether the text was queued.
        """
        if not self._is_running:
            return SpeakResult(
                status="error",
                message="Engine is not running. Call engine.start() first.",
            )

        if not text or not text.strip():
            return SpeakResult(status="skipped", message="Empty text.")

        voice = voice or self._config.default_voice

        msg = SpeakMessage(
            text=text,
            voice=voice,
            style=style,
            priority=priority,
            event_type=event_type,
            client_ip=client_ip,
        )
        depth = self._worker.submit(msg)

        self._record_activity(event_type.name, voice, text)
        self._record_usage(len(text), True)

        return SpeakResult(
            status="queued",
            message=f"Queued for synthesis (voice={voice})",
            queue_depth=depth,
        )

    def speak_event(self, event_json: str, client_ip: str | None = None) -> SpeakResult:
        """Process a structured JSON event through the full pipeline.

        The event is classified, filtered, chunked, synthesized, and played
        — exactly like the ag-voice stdin pipe mode.

        Args:
            event_json: A JSON string representing a stream event, e.g.
                ``'{"type": "message", "content": "Hello"}'``.

        Returns:
            A :class:`SpeakResult`.
        """
        if not self._is_running:
            return SpeakResult(
                status="error",
                message="Engine is not running. Call engine.start() first.",
            )

        msg = EventMessage(event_json=event_json, client_ip=client_ip)
        depth = self._worker.submit(msg)

        self._record_activity('EVENT', 'auto', event_json)
        self._record_usage(len(event_json), True)

        return SpeakResult(
            status="queued",
            message="Event queued for processing",
            queue_depth=depth,
        )

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def set_volume(self, volume: float) -> None:
        """Set playback volume.

        Args:
            volume: Volume level from 0.0 (silent) to 1.0 (full).
        """
        volume = max(0.0, min(1.0, volume))
        self._config.volume = volume
        self._worker.submit(
            ControlMessage(action="set_volume", payload={"volume": volume})
        )
        logger.info("Volume set to %.0f%%", volume * 100)

    def set_speed(self, speed: float) -> None:
        """Set playback speed.

        Args:
            speed: Speed multiplier from 0.5 (slow) to 2.0 (fast).
        """
        speed = max(0.5, min(2.0, speed))
        self._config.speed = speed
        self._worker.submit(
            ControlMessage(action="set_speed", payload={"speed": speed})
        )
        logger.info("Speed set to %.2fx", speed)

    def set_voice(self, event_type: str, voice_name: str) -> None:
        """Change the voice used for a specific event type.

        Args:
            event_type: Event type name (e.g. ``"message"``, ``"error"``).
            voice_name: New voice name (e.g. ``"Kore"``, ``"Fenrir"``).
        """
        self._worker.submit(
            ControlMessage(
                action="set_voice",
                payload={"event_type": event_type, "voice_name": voice_name},
            )
        )

    def flush_queue(self, event_type: str = "") -> None:
        """Clear the audio playback queue.

        Args:
            event_type: Optional event type to flush. Empty string flushes
                all events.
        """
        self._worker.submit(
            ControlMessage(
                action="flush",
                payload={"event_type": event_type},
            )
        )

    def stop_audio(self) -> None:
        """Stop current playback and clear the queue."""
        self._worker.submit(ControlMessage(action="stop"))

    def get_available_providers(self) -> list[str]:
        """Get a list of available TTS provider names.

        Returned in priority / fallback order:
        1. Gemini       — cloud, primary
        2. Jonbox       — self-hosted Coqui VITS
        3. Kokoro       — local Metal-accelerated (MLX)
        4. AVFoundation — macOS native, offline fallback
        """
        return ["Gemini", "Jonbox", "Kokoro", "AVFoundation"]

    def set_tts_provider(self, provider_name: str) -> bool:
        """Switch the TTS provider at runtime."""
        provider_name = provider_name.lower()
        provider = None
        
        if provider_name == "kokoro":
            from gencan_sse.providers.kokoro import KokoroTTSProvider
            provider = KokoroTTSProvider()
        elif provider_name == "gemini":
            from gencan_sse.providers.gemini import GeminiTTSProvider
            provider = GeminiTTSProvider(
                model=self._config.tts_model,
                fallback_models=self._config.tts_fallback_models,
                requests_per_minute=self._config.tts_requests_per_minute,
                round_robin_mode=self._config.tts_round_robin,
            )
        elif provider_name == "jonbox":
            from gencan_sse.providers.jonbox import JonboxTTSProvider
            provider = JonboxTTSProvider(base_url=self._config.jonbox_base_url or "http://localhost:8080")
        elif provider_name == "avfoundation":
            from gencan_sse.providers.avfoundation import AVFoundationTTSProvider
            provider = AVFoundationTTSProvider()

        if provider:
            self._tts_provider = provider
            self._worker.submit(ControlMessage(action="set_provider", payload={"provider": provider}))
            logger.info("Engine TTS provider switched to %s", provider.name)
            return True
        return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> EngineStatus:
        """Get current engine status.

        Returns:
            An :class:`EngineStatus` with runtime information.
        """
        return EngineStatus(
            is_running=self.is_running,
            queue_depth=self._player.queue_depth,
            volume=self._player.volume,
            speed=self._player.speed,
            uptime_seconds=time.time() - self._start_time if self._start_time else 0.0,
            tts_provider=self._tts_provider.name,
            tts_available=self._tts_provider.is_available,
            voices={
                etype.name: name
                for etype, (name, _, _) in self._voice_map.items()
            },
            usage=self.get_usage_stats(),
        )

    # ------------------------------------------------------------------
    # Activity logging & usage tracking
    # ------------------------------------------------------------------

    def get_activity_log(self) -> list[dict]:
        """Return the activity log (most recent entries, up to 50)."""
        return list(self._activity_log)

    def get_usage_stats(self) -> dict:
        """Return a copy of the current usage statistics."""
        return dict(self._usage_stats)

    def _record_activity(
        self,
        event_type: str,
        voice_name: str,
        text: str,
        status: str = "success",
    ) -> None:
        """Append an entry to the activity log, capped at 50 entries."""
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event_type": event_type,
            "voice_name": voice_name,
            "text": text[:200],
            "status": status,
        }
        self._activity_log.append(entry)
        if len(self._activity_log) > 50:
            self._activity_log = self._activity_log[-50:]

    def _record_usage(self, text_len: int, success: bool) -> None:
        """Update usage statistics."""
        self._usage_stats["total_characters"] += text_len
        self._usage_stats["total_requests"] += 1
        if not success:
            self._usage_stats["failed_requests"] += 1
        # $15.00 per 1M characters
        self._usage_stats["estimated_cost_usd"] = (
            self._usage_stats["total_characters"] * 15.0 / 1_000_000
        )

    def _record_chunk_metrics(self, metadata: dict) -> None:
        """Record usage and performance metrics for a rendered chunk."""
        model = metadata.get("model", "unknown")
        provider = metadata.get("provider", "unknown")
        latency_ms = metadata.get("latency_ms", 0.0)
        audio_bytes = metadata.get("audio_bytes", 0)

        # Update per-model stats
        if model not in self._usage_stats["by_model"]:
            self._usage_stats["by_model"][model] = {"requests": 0, "audio_bytes": 0, "total_latency_ms": 0.0}
        
        m_stat = self._usage_stats["by_model"][model]
        m_stat["requests"] += 1
        m_stat["audio_bytes"] += audio_bytes
        m_stat["total_latency_ms"] += latency_ms

        # Update per-provider stats
        if provider not in self._usage_stats["by_provider"]:
            self._usage_stats["by_provider"][provider] = {"requests": 0, "audio_bytes": 0}
        
        p_stat = self._usage_stats["by_provider"][provider]
        p_stat["requests"] += 1
        p_stat["audio_bytes"] += audio_bytes

        # Update global chunk metrics
        cm = self._usage_stats["chunk_metrics"]
        cm["total_latency_ms"] += latency_ms
        cm["total_audio_bytes"] += audio_bytes
        cm["total_chunks"] += 1

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    def drain(self, timeout: float = 30.0) -> bool:
        """Block until the audio queue is empty or *timeout* expires.

        Useful when callers need to wait for all queued speech to finish
        before proceeding (e.g. before program exit).

        Args:
            timeout: Maximum seconds to wait. Defaults to 30.

        Returns:
            ``True`` if the queue drained within the timeout,
            ``False`` if the timeout expired with items still queued.
        """
        if not self._is_running:
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._player.queue_depth == 0:
                return True
            time.sleep(0.1)
        return False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> SpeechEngine:
        """Start the engine when entering a ``with`` block."""
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop the engine when exiting a ``with`` block."""
        self.stop()
