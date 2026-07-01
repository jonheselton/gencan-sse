"""Gemini TTS provider for gencan-sse.

Wraps the Google Gemini TTS API into a :class:`TTSProvider`-compatible class
with production-grade resilience features:

* **Circuit breaker** – per-model tracking that stops calling a model after
  consecutive failures and re-enables it after a cooldown period.
* **Rate limiting** – enforces a configurable outbound request rate (RPM) via
  an async lock + sleep strategy.
* **Fallback models** – automatically cascades through a priority-ordered list
  of Gemini TTS models when the primary model fails.
* **Retry with exponential backoff** – transient errors trigger retries with
  jittered exponential back-off (capped at 30 s).
* **429 awareness** – parses ``retryDelay`` from Gemini error responses and
  uses that value as the circuit-breaker cooldown.
* **Concurrency semaphore** – limits the number of parallel in-flight API
  calls.
* **Optional local TTS endpoint** – when ``GEMINI_API_BASE_URL`` is set, a
  secondary ``genai.Client`` is created for local/self-hosted inference.

Ported from ``ag_voice.tts_client.TTSClient``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum text payload size (in bytes) accepted by the Gemini TTS API.
MAX_TEXT_BYTES: int = 5000


class GeminiTTSProvider:
    """Gemini TTS API wrapper implementing the :class:`TTSProvider` protocol.

    Features
    --------
    - Circuit breaker: stops calling API after consecutive failures.
    - 429-specific handling: reads ``retryDelay`` from API response.
    - Exponential backoff with jitter on transient errors.
    - Concurrency semaphore: limits parallel API calls.
    - Text batching: accepts full text up to 5 KB per request.
    """

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        model: str = "gemini-3.1-flash-tts-preview",
        fallback_models: list[str] | None = None,
        max_concurrent: int = 2,
        max_retries: int = 3,
        circuit_break_threshold: int = 3,
        circuit_break_cooldown: float = 60.0,
        requests_per_minute: float = 10.0,
        round_robin_mode: bool = False,
    ) -> None:
        """Initialise the Gemini TTS provider.

        Args:
            model: Primary Gemini TTS model identifier.
            fallback_models: Optional ordered list of fallback model IDs.
            max_concurrent: Maximum parallel API calls (semaphore size).
            max_retries: Maximum retry attempts on transient errors.
            circuit_break_threshold: Consecutive failures before the circuit
                opens for a given model.
            circuit_break_cooldown: Default seconds to wait before retrying
                after a circuit opens.
            requests_per_minute: Outbound API request rate limit (RPM).
        """
        logger.debug(
            "GeminiTTSProvider.__init__: model=%s, fallback_models=%s, "
            "max_concurrent=%d, max_retries=%d, circuit_threshold=%d, "
            "circuit_cooldown=%.1fs, requests_per_minute=%.1f",
            model,
            fallback_models,
            max_concurrent,
            max_retries,
            circuit_break_threshold,
            circuit_break_cooldown,
            requests_per_minute,
        )

        self._model = model
        self._models: list[str] = [model]
        if fallback_models:
            for m in fallback_models:
                if m not in self._models:
                    self._models.append(m)
        else:
            default_fallbacks = [
                "gemini-3.1-flash-tts-preview",
                "gemini-2.5-flash-preview-tts",
                "gemini-2.5-pro-preview-tts",
            ]
            for m in default_fallbacks:
                if m not in self._models:
                    self._models.append(m)

        # API keys ---------------------------------------------------------
        self._api_key: str = os.environ.get(
            "AI_STUDIO_KEY", os.environ.get("GEMINI_API_KEY", "")
        )
        self._client: Any | None = None

        self._local_base_url: str | None = os.environ.get("GEMINI_API_BASE_URL")
        self._local_client: Any | None = None
        self._local_model_name: str = os.environ.get("GEMINI_LOCAL_MODEL", "local-tts")

        if self._local_base_url:
            if self._local_model_name not in self._models:
                self._models.append(self._local_model_name)

        # Resilience state -------------------------------------------------
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_retries = max_retries
        self._circuit_break_threshold = circuit_break_threshold
        self._circuit_break_cooldown = circuit_break_cooldown
        
        self._round_robin_mode = round_robin_mode
        self._round_robin_idx = 0
        self._round_robin_gemini_idx = 0

        self._states_lock = threading.Lock()
        self._model_states: dict[str, dict[str, float | int]] = {
            m: {"consecutive_failures": 0, "cooldown_until": 0.0}
            for m in self._models
        }

        # Outbound rate-limiting -------------------------------------------
        self._requests_per_minute = requests_per_minute
        self._min_request_interval: float = (
            60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        )
        self._last_request_time: float = 0.0
        self._rate_limit_lock = asyncio.Lock()

        # Client initialisation --------------------------------------------
        if not self._api_key and not self._local_base_url:
            logger.warning(
                "Neither AI_STUDIO_KEY / GEMINI_API_KEY nor GEMINI_API_BASE_URL "
                "set. TTS will return silence. Set the environment variable to "
                "enable speech."
            )
        else:
            try:
                from google import genai  # type: ignore[import-untyped]

                if self._api_key:
                    logger.debug(
                        "API key found (%d chars), initializing genai client",
                        len(self._api_key),
                    )
                    self._client = genai.Client(api_key=self._api_key)

                if self._local_base_url:
                    logger.debug(
                        "GEMINI_API_BASE_URL found (%s), initializing local "
                        "genai client",
                        self._local_base_url,
                    )
                    self._local_client = genai.Client(
                        api_key=os.environ.get("GEMINI_LOCAL_API_KEY", "local_dummy_key"),
                        http_options={"base_url": self._local_base_url},
                    )

                logger.info(
                    "Gemini TTS provider initialized — primary model: %s, "
                    "fallback models: %s",
                    self._model,
                    self._models[1:],
                )
            except ImportError:
                logger.warning(
                    "google-genai package not installed. Gemini TTS disabled."
                )
            except Exception as exc:
                logger.warning("Failed to initialize Gemini TTS client: %s", exc)

    # ------------------------------------------------------ TTSProvider API

    @property
    def name(self) -> str:
        """Human-readable name of this provider."""
        return "gemini"

    @property
    def is_available(self) -> bool:
        """Whether at least one API client is initialised and usable."""
        return self._client is not None or self._local_client is not None

    async def synthesize(
        self,
        text: str,
        voice: str = "Kore",
        style: str = "",
    ) -> tuple[bytes, dict]:
        """Synthesize *text* to raw PCM audio bytes.

        Respects circuit breaker, concurrency limits, and rate-limit backoff.

        Args:
            text: The text to speak (up to 5 KB).
            voice: Gemini TTS voice name (e.g. ``"Kore"``, ``"Puck"``).
            style: Style / audio tags to prepend (e.g. ``"[alert] "``).

        Returns:
            A tuple of (PCM audio bytes, metadata dict).
            Returns (b"", {}) on failure or during circuit-breaker cooldown.
        """
        logger.debug(
            "synthesize called: voice=%s, style=%r, text_len=%d, "
            "has_client=%s, has_local_client=%s",
            voice,
            style,
            len(text) if text else 0,
            self._client is not None,
            self._local_client is not None,
        )

        if not (self._client or self._local_client) or not text.strip():
            logger.debug("synthesize: early return (no client or empty text)")
            return b"", {}

        # Circuit breaker check
        if self.is_circuit_open:
            logger.debug(
                "All circuits open — skipping TTS (%.0fs remaining)",
                self.cooldown_remaining,
            )
            return b"", {}

        full_text = f"{style}{text}" if style else text
        text_bytes = len(full_text.encode("utf-8"))
        logger.debug(
            "synthesize: full_text_bytes=%d (limit=%d)",
            text_bytes,
            MAX_TEXT_BYTES,
        )

        # Truncate if over API limit
        if text_bytes > MAX_TEXT_BYTES:
            encoded = full_text.encode("utf-8")
            boundary = MAX_TEXT_BYTES
            while boundary > 0 and (encoded[boundary] & 0xC0) == 0x80:
                boundary -= 1
            full_text = encoded[:boundary].decode("utf-8", errors="ignore")
            logger.warning(
                "Text truncated to %d bytes for TTS API limit", len(encoded[:boundary])
            )

        # Enforce self-imposed rate limiting
        if self._min_request_interval > 0:
            sleep_time = 0.0
            async with self._rate_limit_lock:
                now = time.time()
                target_time = max(now, self._last_request_time + self._min_request_interval)
                if target_time > now:
                    sleep_time = target_time - now
                self._last_request_time = target_time

            if sleep_time > 0:
                logger.info(
                    "Rate limiting outbound TTS API call: sleeping for "
                    "%.2f seconds",
                    sleep_time,
                )
                await asyncio.sleep(sleep_time)

        # Acquire semaphore to limit concurrent API calls
        logger.debug("synthesize: acquiring semaphore")
        async with self._semaphore:
            logger.debug(
                "synthesize: semaphore acquired, calling "
                "_synthesize_with_fallback"
            )
            return await self._synthesize_with_fallback(full_text, voice)

    # ------------------------------------------------- circuit-breaker logic

    @property
    def is_circuit_open(self) -> bool:
        """Whether the circuit breaker is open (all models blocking)."""
        return all(self.is_model_circuit_open(m) for m in self._models)

    def is_model_circuit_open(self, model: str) -> bool:
        """Whether the circuit breaker is open for a specific model."""
        with self._states_lock:
            state = self._model_states.get(model)
            if not state:
                return False
            cooldown_until = float(state["cooldown_until"])
            if cooldown_until <= 0:
                return False
            if time.time() >= cooldown_until:
                # Cooldown expired — reset
                state["cooldown_until"] = 0.0
                state["consecutive_failures"] = 0
                logger.info(
                    "Circuit breaker reset for model %s — resuming TTS calls",
                    model,
                )
                return False
            return True

    @property
    def cooldown_remaining(self) -> float:
        """Seconds remaining until at least one model exits cooldown."""
        if not self.is_circuit_open:
            return 0.0
        remainings = [self.model_cooldown_remaining(m) for m in self._models]
        return min(remainings) if remainings else 0.0

    def model_cooldown_remaining(self, model: str) -> float:
        """Seconds remaining in cooldown for *model*, or ``0``."""
        with self._states_lock:
            state = self._model_states.get(model)
            if not state or float(state["cooldown_until"]) <= 0:
                return 0.0
            remaining = float(state["cooldown_until"]) - time.time()
            return max(0.0, remaining)

    def _open_circuit(self, cooldown_seconds: float) -> None:
        """Open the circuit breaker for the primary model (compat helper)."""
        self._open_model_circuit(self._model, cooldown_seconds)

    def _open_model_circuit(self, model: str, cooldown_seconds: float) -> None:
        """Open the circuit breaker for *model* for *cooldown_seconds*."""
        with self._states_lock:
            state = self._model_states.get(model)
            if state:
                state["cooldown_until"] = time.time() + cooldown_seconds
                logger.warning(
                    "Circuit breaker OPEN for model %s — blocking TTS for "
                    "%.0fs (%d consecutive failures)",
                    model,
                    cooldown_seconds,
                    state["consecutive_failures"],
                )

    # -------------------------------------------------- retry-delay parsing

    @staticmethod
    def _parse_retry_delay(error: Exception) -> float | None:
        """Try to parse ``retryDelay`` from a Gemini API error response.

        Looks for patterns such as ``'retry in 1h12m7.98s'`` or
        ``'"retryDelay": "4327s"'`` in the stringified error.

        Args:
            error: The exception raised by the Gemini API client.

        Returns:
            Parsed delay in seconds, or ``None`` if no delay could be
            extracted.
        """
        error_str = str(error)

        # Match "retryDelay": "4327s" pattern
        match = re.search(r'"retryDelay":\s*"(\d+)s"', error_str)
        if match:
            return float(match.group(1))

        # Match "retry in XhYmZ.Ws" pattern
        match = re.search(r"retry in (\d+)h(\d+)m([\d.]+)s", error_str)
        if match:
            hours = float(match.group(1))
            minutes = float(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds

        # Match "retry in YmZ.Ws" pattern (no hours)
        match = re.search(r"retry in (\d+)m([\d.]+)s", error_str)
        if match:
            minutes = float(match.group(1))
            seconds = float(match.group(2))
            return minutes * 60 + seconds

        return None

    # --------------------------------------------------- fallback + retry

    async def _synthesize_with_fallback(
        self,
        full_text: str,
        voice_name: str,
    ) -> tuple[bytes, dict]:
        """Attempt synthesis using each model in priority order."""
        models_to_try = self._models

        if getattr(self, "_round_robin_mode", False) and self._models:
            gemini_models = [m for m in self._models if m != self._local_model_name]
            has_local = self._local_model_name in self._models

            if has_local and gemini_models:
                if self._round_robin_idx % 2 == 1:
                    primary = self._local_model_name
                else:
                    primary = gemini_models[self._round_robin_gemini_idx % len(gemini_models)]
                    self._round_robin_gemini_idx += 1
                self._round_robin_idx += 1
                models_to_try = [primary] + [m for m in self._models if m != primary]
            elif gemini_models:
                primary = gemini_models[self._round_robin_idx % len(gemini_models)]
                self._round_robin_idx += 1
                models_to_try = [primary] + [m for m in self._models if m != primary]

        for model in models_to_try:
            if self.is_model_circuit_open(model):
                logger.debug(
                    "Model %s circuit is open — trying next fallback", model
                )
                continue

            audio_data, metadata = await self._synthesize_with_model_retry(
                model, full_text, voice_name
            )
            if audio_data:
                return audio_data, metadata

            # Failed and possibly triggered circuit — fall through
            logger.warning(
                "Synthesis with model %s failed, trying fallback model", model
            )

        logger.error("All TTS models failed to synthesize audio.")
        return b"", {}

    async def _synthesize_with_model_retry(
        self,
        model: str,
        full_text: str,
        voice_name: str,
    ) -> tuple[bytes, dict]:
        """Call the API for *model* with retries and exponential backoff."""
        state = self._model_states[model]

        for attempt in range(self._max_retries):
            try:
                logger.debug(
                    "Calling API for model %s (attempt %d/%d)",
                    model,
                    attempt + 1,
                    self._max_retries,
                )
                api_t0 = time.time()

                client = (
                    self._local_client if model == self._local_model_name else self._client
                )
                if not client:
                    raise ValueError(
                        f"Client for model '{model}' is not initialized."
                    )

                # Strip style prefixes for non-Gemini models so the TTS
                # engine doesn't read instructions aloud.
                request_text = full_text
                if not model.startswith("gemini"):
                    request_text = re.sub(
                        r"^\[[^\]]*\]\s*", "", full_text
                    )
                    logger.debug(
                        "Stripped style prefix for non-Gemini model %s: "
                        "%r -> %r",
                        model,
                        full_text,
                        request_text,
                    )

                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=request_text,
                    config={
                        "response_modalities": ["AUDIO"],
                        "speech_config": {
                            "voice_config": {
                                "prebuilt_voice_config": {
                                    "voice_name": voice_name,
                                }
                            }
                        },
                    },
                )
                api_elapsed = time.time() - api_t0
                logger.debug(
                    "API responded in %.3fs for model %s", api_elapsed, model
                )

                if (
                    response
                    and response.candidates
                    and response.candidates[0].content
                    and response.candidates[0].content.parts
                ):
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.data:
                            with self._states_lock:
                                state["consecutive_failures"] = 0
                            audio_bytes = len(part.inline_data.data)
                            duration_est = audio_bytes / (24000 * 2)
                            logger.debug(
                                "TTS synthesized %d bytes (~%.1fs audio) for "
                                "voice=%s model=%s, api_time=%.3fs",
                                audio_bytes,
                                duration_est,
                                voice_name,
                                model,
                                api_elapsed,
                            )
                            metadata = {
                                "model": model,
                                "provider": self.name,
                                "latency_ms": api_elapsed * 1000,
                                "audio_bytes": audio_bytes,
                            }
                            return part.inline_data.data, metadata

                logger.warning(
                    "TTS response contained no audio data for model %s", model
                )
                with self._states_lock:
                    state["consecutive_failures"] += 1
                    failures = int(state["consecutive_failures"])
                if failures >= self._circuit_break_threshold:
                    self._open_model_circuit(model, self._circuit_break_cooldown)
                return b"", {}

            except Exception as exc:
                error_str = str(exc)
                is_rate_limit = False
                if hasattr(exc, "code") and getattr(exc, "code") == 429:
                    is_rate_limit = True
                elif hasattr(exc, "status_code") and getattr(exc, "status_code") == 429:
                    is_rate_limit = True
                else:
                    is_rate_limit = (
                        "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                    )
                
                with self._states_lock:
                    state["consecutive_failures"] = (
                        int(state["consecutive_failures"]) + 1
                    )
                    failures = int(state["consecutive_failures"])

                logger.debug(
                    "Exception on model %s attempt %d/%d — type=%s, "
                    "is_rate_limit=%s, failures=%d, error=%s",
                    model,
                    attempt + 1,
                    self._max_retries,
                    type(exc).__name__,
                    is_rate_limit,
                    failures,
                    error_str[:200],
                )

                if is_rate_limit:
                    retry_delay = self._parse_retry_delay(exc)
                    cooldown = (
                        retry_delay
                        if retry_delay
                        else self._circuit_break_cooldown
                    )
                    logger.warning(
                        "Rate limited (429) on model %s. Opening circuit "
                        "for %.0fs.",
                        model,
                        cooldown,
                    )
                    self._open_model_circuit(model, cooldown)
                    return b"", {}  # Stop retrying this model on 429

                # Check circuit breaker threshold for other errors
                if failures >= self._circuit_break_threshold:
                    self._open_model_circuit(model, self._circuit_break_cooldown)
                    return b"", {}

                if attempt < self._max_retries - 1:
                    delay = min(2**attempt + random.uniform(0, 1), 30)
                    logger.warning(
                        "TTS attempt %d/%d failed for model %s: %s. "
                        "Retrying in %.1fs...",
                        attempt + 1,
                        self._max_retries,
                        model,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "TTS failed for model %s after %d attempts: %s.",
                        model,
                        self._max_retries,
                        exc,
                    )

        return b"", {}
