"""Tests for gencan_sse.providers.gemini module."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from gencan_sse.providers.gemini import GeminiTTSProvider, MAX_TEXT_BYTES


class TestGeminiTTSProviderInit:
    """Tests for GeminiTTSProvider initialization."""

    def test_name(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                assert provider.name == "gemini"

    def test_not_available_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            provider = GeminiTTSProvider()
            assert provider.is_available is False

    def test_available_with_key(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                assert provider.is_available is True

    def test_default_model(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                assert provider._model == "gemini-3.1-flash-tts-preview"

    def test_custom_model(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider(model="custom-model")
                assert provider._model == "custom-model"

    def test_fallback_models(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider(
                    fallback_models=["model-a", "model-b"]
                )
                assert "model-a" in provider._models
                assert "model-b" in provider._models


class TestGeminiTTSProviderSynthesize:
    """Tests for GeminiTTSProvider.synthesize()."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                result = await provider.synthesize("")
                assert result == b""

    @pytest.mark.asyncio
    async def test_whitespace_text_returns_empty(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                result = await provider.synthesize("   ")
                assert result == b""

    @pytest.mark.asyncio
    async def test_no_client_returns_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            provider = GeminiTTSProvider()
            result = await provider.synthesize("hello")
            assert result == b""


class TestParseRetryDelay:
    """Tests for GeminiTTSProvider._parse_retry_delay()."""

    def test_seconds_format(self):
        error = Exception('"retryDelay": "4327s"')
        delay = GeminiTTSProvider._parse_retry_delay(error)
        assert delay == 4327.0

    def test_hms_format(self):
        error = Exception("retry in 1h12m7.98s")
        delay = GeminiTTSProvider._parse_retry_delay(error)
        assert delay == pytest.approx(3600 + 720 + 7.98, abs=0.01)

    def test_ms_format(self):
        error = Exception("retry in 5m30.5s")
        delay = GeminiTTSProvider._parse_retry_delay(error)
        assert delay == pytest.approx(330.5, abs=0.01)

    def test_no_delay(self):
        error = Exception("some random error")
        delay = GeminiTTSProvider._parse_retry_delay(error)
        assert delay is None


class TestCircuitBreaker:
    """Tests for circuit breaker behavior."""

    def test_circuit_initially_closed(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                assert provider.is_circuit_open is False

    def test_open_circuit(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                # Open circuit for all models
                for model in provider._models:
                    provider._open_model_circuit(model, 60.0)
                assert provider.is_circuit_open is True

    def test_cooldown_remaining(self):
        with patch.dict("os.environ", {"AI_STUDIO_KEY": "test-key"}):
            with patch("google.genai.Client"):
                provider = GeminiTTSProvider()
                provider._open_model_circuit(provider._model, 60.0)
                remaining = provider.model_cooldown_remaining(provider._model)
                assert remaining > 0
                assert remaining <= 60.0
