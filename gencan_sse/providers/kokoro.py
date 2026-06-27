"""Kokoro TTS provider using MLX for gencan-sse."""

from __future__ import annotations

import logging
import time
import io
import wave
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)


class KokoroTTSProvider:
    """Kokoro TTS API wrapper using MLX for local inference."""

    def __init__(self, model_path: str = "prince-canuma/Kokoro-82M") -> None:
        """Initialise the Kokoro TTS provider."""
        self._model_path = model_path
        self._available = False
        self._generate_fn: Any | None = None
        
        try:
            from mlx_audio.tts.generate import generate_audio
            self._generate_fn = generate_audio
            self._available = True
            logger.info("Kokoro MLX TTS provider initialized.")
        except ImportError:
            logger.warning("mlx-audio package not installed. Kokoro TTS disabled.")
        except Exception as exc:
            logger.warning("Failed to initialize Kokoro MLX TTS client: %s", exc)

    @property
    def name(self) -> str:
        return "kokoro"

    @property
    def is_available(self) -> bool:
        return self._available

    async def synthesize(
        self,
        text: str,
        voice: str = "af_heart",
        style: str = "",
    ) -> tuple[bytes, dict]:
        """Synthesize text to raw PCM audio bytes."""
        if not self._available or not self._generate_fn or not text.strip():
            return b"", {}

        full_text = f"{style}{text}" if style else text

        try:
            import asyncio
            api_t0 = time.time()
            
            # mlx-audio's generate_audio currently prefers writing to a file in the simplest API.
            # We'll use a temporary file to capture the WAV, then read the raw PCM data.
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            # Generate audio in a separate thread to avoid blocking the asyncio event loop
            await asyncio.to_thread(
                self._generate_fn,
                text=full_text,
                model_path=self._model_path,
                voice=voice,
                speed=1.0,
                audio_format="wav",
                file_prefix=tmp_path.replace(".wav", "")
            )
            
            # The generate_audio function might append .wav to the prefix
            actual_path = tmp_path
            if not os.path.exists(actual_path) and os.path.exists(f"{tmp_path}.wav"):
                actual_path = f"{tmp_path}.wav"
            elif not os.path.exists(actual_path) and os.path.exists(tmp_path.replace(".wav", "") + ".wav"):
                actual_path = tmp_path.replace(".wav", "") + ".wav"

            pcm_data = b""
            if os.path.exists(actual_path):
                with wave.open(actual_path, "rb") as wf:
                    # Read frames. Note: Kokoro is typically 24kHz.
                    # Our base provider expects 16-bit signed PCM.
                    pcm_data = wf.readframes(wf.getnframes())
                os.remove(actual_path)
            
            if tmp_path != actual_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

            api_elapsed = time.time() - api_t0
            
            if pcm_data:
                return pcm_data, {
                    "model": "Kokoro-82M (MLX)",
                    "provider": self.name,
                    "latency_ms": api_elapsed * 1000,
                    "audio_bytes": len(pcm_data),
                }
                
            logger.warning("Kokoro TTS generated empty audio.")
            return b"", {}
        except Exception as exc:
            logger.warning("Kokoro TTS failed: %s", exc)
            return b"", {}
