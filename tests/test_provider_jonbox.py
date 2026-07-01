"""Tests for gencan_sse.providers.jonbox module."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

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
        import base64
        encoded_data = base64.b64encode(b"audio_data").decode("utf-8")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "data": encoded_data
                                }
                            }
                        ]
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("google.genai.Client"):
            with patch("httpx.AsyncClient") as mock_http_client:
                mock_post = AsyncMock(return_value=mock_response)
                mock_http_client.return_value.post = mock_post
                # Keep compatibility with context manager mocking if needed
                mock_instance = MagicMock()
                mock_instance.post = mock_post
                mock_http_client.return_value.__aenter__.return_value = mock_instance

                provider = JonboxTTSProvider(base_url="http://localhost:8080")
                result, metadata = await provider.synthesize("Hello")
                
                assert result == b"audio_data"
                assert metadata["provider"] == "jonbox"
                assert metadata["model"] == "jonbox-coqui"
                assert metadata["audio_bytes"] == len(b"audio_data")

                mock_post.assert_called_once()
