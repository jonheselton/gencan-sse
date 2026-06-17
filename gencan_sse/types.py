"""Core type contracts for gencan-sse.

Defines the shared data structures used across all gencan_sse modules:
event classification, audio chunks, voice configuration, engine status,
and speak results.

Ported from ag_voice.types with additions for the standalone engine API.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class EventType(Enum):
    """Classified event types.

    Each variant maps to a category of content that can flow through
    the speech synthesis pipeline.
    """

    MESSAGE = "message"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    SKIP = "skip"


class Priority(Enum):
    """Audio queue priority levels.

    Lower numeric value = higher priority.  When the audio queue is
    congested, higher-priority items are played first.
    """

    ERROR = 1
    RESPONSE = 2
    TOOL = 3
    THINKING = 4


@dataclass
class ClassifiedEvent:
    """A parsed and classified event.

    Produced by the classifier and consumed by downstream stages
    (filtering, chunking, TTS synthesis).

    Attributes:
        event_type: The classified category of this event.
        text: The extracted textual content.
        raw: The original raw event dictionary (preserved for debugging).
        priority: Queue priority derived from event_type.
    """

    event_type: EventType
    text: str
    raw: dict
    priority: Priority = Priority.RESPONSE


@dataclass
class AudioChunk:
    """A chunk of PCM audio data ready for playback.

    Attributes:
        pcm_data: Raw PCM bytes (signed 16-bit LE, mono, 24 kHz by default).
        priority: Queue priority for playback ordering.
        event_type: The event category that produced this audio.
        timestamp: Wall-clock time when this chunk was created.
    """

    pcm_data: bytes
    priority: Priority
    event_type: EventType
    timestamp: float = field(default_factory=time.time)


@dataclass
class VoiceMapping:
    """Configuration for a single voice mapping.

    Maps an event type to a TTS voice name, optional style prefix,
    and queue priority.

    Attributes:
        voice_name: The TTS voice identifier (e.g. ``"Kore"``).
        style_prefix: Text prepended to content before TTS synthesis
            to influence speaking style (e.g. ``"[thoughtfully] "``).
        enabled: Whether this voice mapping is active.  Disabled
            mappings cause their event type to be silently skipped.
        priority: Numeric priority (lower = higher priority).
    """

    voice_name: str
    style_prefix: str = ""
    enabled: bool = True
    priority: int = 2


@dataclass
class SpeakResult:
    """Result returned by ``engine.speak()``.

    Attributes:
        status: One of ``"queued"``, ``"skipped"``, or ``"error"``.
        message: Human-readable detail about the result.
        queue_depth: Number of items in the audio queue after this call.
    """

    status: str  # "queued", "skipped", "error"
    message: str = ""
    queue_depth: int = 0


@dataclass
class EngineStatus:
    """Status information about the engine.

    Returned by ``engine.status()`` to expose runtime state for
    monitoring and debugging.

    Attributes:
        is_running: Whether the engine's playback loop is active.
        queue_depth: Number of audio chunks waiting for playback.
        volume: Current volume level (0.0–1.0).
        speed: Current playback speed multiplier.
        uptime_seconds: Seconds since the engine was started.
        tts_provider: Name/model of the active TTS provider.
        tts_available: Whether the TTS provider is reachable.
        voices: Mapping of event-type names to their active voice names.
    """

    is_running: bool
    queue_depth: int
    volume: float
    speed: float
    uptime_seconds: float
    tts_provider: str
    tts_available: bool
    voices: dict = field(default_factory=dict)
