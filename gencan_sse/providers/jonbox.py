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
        self._httpx_client = None
        
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
            import httpx
            import base64
            api_t0 = time.time()
            request_text = re.sub(r"^\[[^\]]*\]\s*", "", full_text)
            
            # Map Gemini voice names to Coqui voice names if needed
            vmap = {
                "kore": "jenny",
                "zephyr": "p303",
                "enceladus": "p303",
                "puck": "p294",
                "charon": "p310",
                "fenrir": "ljspeech"
            }
            mapped_voice = vmap.get(voice.lower().strip(), "jenny")
            
            payload = {
                "contents": [{"parts": [{"text": request_text}]}],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": mapped_voice}
                    }
                }
            }
            
            if self._httpx_client is None:
                self._httpx_client = httpx.AsyncClient()
            resp = await self._httpx_client.post(
                f"{self._base_url}/v1beta/models/jonbox-tts:generateContent",
                json=payload,
                timeout=60.0
            )
            resp.raise_for_status()
            data = resp.json()
                
            api_elapsed = time.time() - api_t0
            
            pcm_data = b""
            if (
                data.get("candidates") and 
                data["candidates"][0].get("content") and 
                data["candidates"][0]["content"].get("parts")
            ):
                for part in data["candidates"][0]["content"]["parts"]:
                    if part.get("inlineData") and part["inlineData"].get("data"):
                        encoded_audio = part["inlineData"]["data"]
                        pcm_data = base64.b64decode(encoded_audio)
                        break
                
            if pcm_data:
                return pcm_data, {
                    "model": "jonbox-coqui",
                    "provider": self.name,
                    "latency_ms": api_elapsed * 1000,
                    "audio_bytes": len(pcm_data),
                }
            
            logger.warning("Jonbox TTS returned empty audio.")
            return b"", {}
        except Exception as exc:
            logger.warning("Jonbox TTS failed: %s", exc)
            return b"", {}
