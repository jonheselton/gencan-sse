"""TTS provider abstraction for gencan-sse.

Provider priority / fallback order:
1. Gemini        — cloud, primary
2. Jonbox        — self-hosted Coqui VITS
3. Kokoro        — local Metal-accelerated (MLX)
4. AVFoundation  — macOS native, offline fallback
5. Vertex AI     — cloud, theoretical (disabled due to cost)
"""

from gencan_sse.providers.base import TTSProvider
from gencan_sse.providers.gemini import GeminiTTSProvider
from gencan_sse.providers.jonbox import JonboxTTSProvider
from gencan_sse.providers.kokoro import KokoroTTSProvider
from gencan_sse.providers.avfoundation import AVFoundationTTSProvider

__all__ = [
    "TTSProvider",
    "GeminiTTSProvider",
    "JonboxTTSProvider",
    "KokoroTTSProvider",
    "AVFoundationTTSProvider",
]
