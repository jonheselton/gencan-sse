"""Jonbox TTS provider for gencan-sse.

A simple TTS provider that forwards requests to a Jonbox endpoint.
"""

from __future__ import annotations

import logging
import asyncio
from typing import Any

logger = logging.getLogger(__name__)

class JonboxTTSProvider:
    """Jonbox TTS API wrapper implementing the TTSProvider protocol."""

    def __init__(self, base_url: str | None = None) -> None:
        """Initialise the Jonbox TTS provider."""
        self._base_url = base_url
        self._client: Any | None = None
        
        if not self._base_url:
            logger.warning("Jonbox base URL not provided. TTS will return silence.")
        else:
            try:
                from google import genai
                logger.debug("Initializing Jonbox genai client at %s", self._base_url)
                self._client = genai.Client(
                    api_key="jonbox_dummy_key",
                    http_options={"base_url": self._base_url},
                )
                logger.info("Jonbox TTS provider initialized")
            except ImportError:
                logger.warning("google-genai package not installed. Jonbox TTS disabled.")
            except Exception as exc:
                logger.warning("Failed to initialize Jonbox TTS client: %s", exc)

    @property
    def name(self) -> str:
        return "jonbox"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def synthesize(
        self,
        text: str,
        voice: str = "Kore",
        style: str = "",
    ) -> tuple[bytes, dict]:
        """Synthesize *text* to raw PCM audio bytes."""
        if not self._client or not text.strip():
            return b"", {}

        full_text = f"{style}{text}" if style else text

        try:
            import re
            import time
            api_t0 = time.time()
            request_text = re.sub(r"^\[[^\]]*\]\s*", "", full_text)
            
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model="jonbox-tts",
                contents=request_text,
                config={
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {"voice_name": voice}
                        }
                    },
                },
            )
            api_elapsed = time.time() - api_t0

            if (
                response and response.candidates and 
                response.candidates[0].content and 
                response.candidates[0].content.parts
            ):
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        audio_bytes = len(part.inline_data.data)
                        return part.inline_data.data, {
                            "model": "jonbox-tts",
                            "provider": self.name,
                            "latency_ms": api_elapsed * 1000,
                            "audio_bytes": audio_bytes,
                        }
            
            logger.warning("Jonbox TTS response contained no audio data.")
            return b"", {}
        except Exception as exc:
            logger.warning("Jonbox TTS failed: %s", exc)
            return b"", {}
