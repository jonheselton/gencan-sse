"""Tests for the Kokoro MLX TTS Provider."""

import pytest
from gencan_sse.providers.kokoro import KokoroTTSProvider

@pytest.mark.asyncio
async def test_kokoro_provider_initialization():
    """Test that the provider initializes gracefully."""
    provider = KokoroTTSProvider()
    assert provider.name == "kokoro"
    # is_available might be False if mlx-audio is not installed
    # which is completely fine for a graceful fallback
    print(f"Provider available: {provider.is_available}")

@pytest.mark.asyncio
async def test_kokoro_provider_synthesis():
    """Test synthesis yields PCM data if available."""
    provider = KokoroTTSProvider()
    
    if not provider.is_available:
        pytest.skip("mlx-audio not installed, skipping synthesis test.")
        
    audio_bytes, metadata = await provider.synthesize(text="Testing Kokoro", voice="af_heart")
    
    assert isinstance(audio_bytes, bytes)
    assert len(audio_bytes) > 0, "Audio bytes should not be empty."
    assert "model" in metadata
    assert metadata["model"] == "Kokoro-82M (MLX)"
    assert metadata["provider"] == "kokoro"


def test_kokoro_voice_resolution():
    """Gemini names and junk fall back to the default; Kokoro IDs pass through."""
    provider = KokoroTTSProvider.__new__(KokoroTTSProvider)
    provider._default_voice = "bf_emma"
    assert provider.resolve_voice("Kore") == "bf_emma"
    assert provider.resolve_voice("Puck") == "bf_emma"
    assert provider.resolve_voice("") == "bf_emma"
    assert provider.resolve_voice("nonsense") == "bf_emma"
    assert provider.resolve_voice("af_heart") == "af_heart"
    assert provider.resolve_voice("bm_george") == "bm_george"
