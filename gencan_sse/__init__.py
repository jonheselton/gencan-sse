"""gencan_sse — GenCan Speech Synthesis Engine.

A standalone, reusable TTS pipeline with a synchronous API,
internal message queue, and pluggable TTS providers.

Quick start::

    from gencan_sse import SpeechEngine

    engine = SpeechEngine()
    engine.start()
    engine.speak("Hello from GenCan!")
    engine.stop()

Or as a context manager::

    from gencan_sse import SpeechEngine

    with SpeechEngine() as engine:
        engine.speak("Hello from GenCan!")
"""

__version__ = "0.1.0"

from gencan_sse.engine import SpeechEngine
from gencan_sse.config import EngineConfig
from gencan_sse.types import (
    AudioChunk,
    ClassifiedEvent,
    EngineStatus,
    EventType,
    Priority,
    SpeakResult,
    VoiceMapping,
)
from gencan_sse.providers.base import TTSProvider

__all__ = [
    "SpeechEngine",
    "EngineConfig",
    "TTSProvider",
    "AudioChunk",
    "ClassifiedEvent",
    "EngineStatus",
    "EventType",
    "Priority",
    "SpeakResult",
    "VoiceMapping",
]
