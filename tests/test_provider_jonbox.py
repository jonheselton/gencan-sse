"""Tests for gencan_sse.providers.jonbox module."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from gencan_sse.providers.jonbox import JonboxTTSProvider

class TestJonboxTTSProviderInit:
    """Tests for JonboxTTSProvider initialization."""

    def test_name(self):
        with patch("google.genai.Client"):
            provider = JonboxTTSProvider(base_url="http://localhost:8080")
            assert provider.name == "jonbox"

    def test_not_available_without_url(self):
        provider = JonboxTTSProvider(base_url=None)
        assert provider.is_available is False

    def test_available_with_url(self):
        with patch("google.genai.Client"):
            provider = JonboxTTSProvider(base_url="http://localhost:8080")
            assert provider.is_available is True

class TestJonboxTTSProviderSynthesize:
    """Tests for JonboxTTSProvider.synthesize()."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self):
        with patch("google.genai.Client"):
            provider = JonboxTTSProvider(base_url="http://localhost:8080")
            result = await provider.synthesize("")
            assert result == (b"", {})

    @pytest.mark.asyncio
    async def test_whitespace_text_returns_empty(self):
        with patch("google.genai.Client"):
            provider = JonboxTTSProvider(base_url="http://localhost:8080")
            result = await provider.synthesize("   ")
            assert result == (b"", {})

    @pytest.mark.asyncio
    async def test_no_client_returns_empty(self):
        provider = JonboxTTSProvider(base_url=None)
        result = await provider.synthesize("hello")
        assert result == (b"", {})
        
    @pytest.mark.asyncio
    async def test_synthesize_success(self):
        with patch("google.genai.Client") as mock_client:
            mock_instance = mock_client.return_value
            mock_response = MagicMock()
            mock_part = MagicMock()
            mock_part.inline_data.data = b"audio_data"
            mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
            mock_instance.models.generate_content.return_value = mock_response

            provider = JonboxTTSProvider(base_url="http://localhost:8080")
            result, metadata = await provider.synthesize("Hello")
            
            assert result == b"audio_data"
            assert metadata["provider"] == "jonbox"
            assert metadata["model"] == "jonbox-tts"
            assert metadata["audio_bytes"] == len(b"audio_data")

            mock_instance.models.generate_content.assert_called_once()
