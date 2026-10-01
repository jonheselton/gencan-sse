"""Kokoro TTS provider using MLX for gencan-sse."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "prince-canuma/Kokoro-82M"
DEFAULT_VOICE = "bf_emma"

# Gemini voice names (used by the default voice config and ag-voice) have no
# Kokoro equivalent, so they all resolve to the provider's default voice.
_GEMINI_VOICES = {"Kore", "Zephyr", "Puck", "Charon", "Fenrir"}

# Kokoro voice IDs start with a language letter and a gender letter,
# e.g. "af_heart" (American female) or "bf_emma" (British female).
_LANG_CODES = set("abefhijpz")


def _use_bundled_espeak() -> None:
    """Point phonemizer at the espeak-ng bundled by ``espeakng-loader``.

    misaki falls back to espeak for out-of-vocabulary words.  Without this,
    phonemizer may pick up an old system ``espeak`` (< 1.49) and fail with
    "tie option only compatible with espeak>=1.49".
    """
    try:
        import espeakng_loader
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
    except ImportError:
        return
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())


def _is_kokoro_voice(voice: str) -> bool:
    return len(voice) > 3 and voice[0] in _LANG_CODES and voice[1] in "fm" and voice[2] == "_"


class KokoroTTSProvider:
    """Kokoro TTS via MLX, with the model kept loaded between calls.

    The default voice can be overridden with the ``KOKORO_VOICE`` environment
    variable.  Kokoro voice IDs passed to :meth:`synthesize` are used as-is;
    anything else (e.g. Gemini voice names) falls back to the default voice.
    """

    def __init__(self, model_path: str = DEFAULT_MODEL, default_voice: str | None = None) -> None:
        """Initialise the provider and load the model into memory."""
        self._model_path = model_path
        self._default_voice = default_voice or os.environ.get("KOKORO_VOICE") or DEFAULT_VOICE
        self._available = False
        self._model: Any | None = None
        # model.generate is not safe to run concurrently.
        self._lock = threading.Lock()

        try:
            _use_bundled_espeak()
            from mlx_audio.tts.utils import load_model
            self._model = load_model(model_path=model_path)
            self._available = True
            logger.info(
                "Kokoro MLX TTS provider initialized (model=%s, default voice=%s).",
                model_path, self._default_voice,
            )
        except ImportError:
            logger.warning("mlx-audio package not installed. Kokoro TTS disabled.")
        except Exception as exc:
            logger.warning("Failed to initialize Kokoro MLX TTS: %s", exc)

    @property
    def name(self) -> str:
        return "kokoro"

    @property
    def is_available(self) -> bool:
        return self._available

    def resolve_voice(self, voice: str) -> str:
        """Map a requested voice name to a Kokoro voice ID."""
        if voice and voice not in _GEMINI_VOICES and _is_kokoro_voice(voice):
            return voice
        return self._default_voice

    def _generate_pcm(self, text: str, voice: str) -> bytes:
        import numpy as np

        parts = []
        with self._lock:
            for result in self._model.generate(text, voice=voice, speed=1.0, lang_code=voice[0]):
                parts.append(np.asarray(result.audio))
        if not parts:
            return b""
        audio = np.concatenate(parts)
        return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        style: str = "",
    ) -> tuple[bytes, dict]:
        """Synthesize text to raw 24 kHz 16-bit mono PCM.

        ``style`` is ignored: Kokoro has no style tags and would read
        Gemini-style prefixes such as "[thoughtfully] " aloud.
        """
        if not self._available or self._model is None or not text.strip():
            return b"", {}

        kokoro_voice = self.resolve_voice(voice)
        try:
            t0 = time.time()
            pcm = await asyncio.to_thread(self._generate_pcm, text, kokoro_voice)
            elapsed = time.time() - t0
        except Exception as exc:
            logger.warning("Kokoro TTS failed: %s", exc)
            return b"", {}

        if not pcm:
            logger.warning("Kokoro TTS generated empty audio.")
            return b"", {}
        return pcm, {
            "model": "Kokoro-82M (MLX)",
            "provider": self.name,
            "voice": kokoro_voice,
            "latency_ms": elapsed * 1000,
            "audio_bytes": len(pcm),
        }
