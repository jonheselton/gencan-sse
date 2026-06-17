"""Base TTS provider protocol.

Defines the ``TTSProvider`` structural-typing interface that all TTS backends
must satisfy.  Because it is decorated with ``@runtime_checkable``, you can
use ``isinstance(obj, TTSProvider)`` to verify conformance at runtime.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSProvider(Protocol):
    """Interface for TTS backends.

    Implement this protocol to add a new TTS engine to gencan-sse.
    The engine will call :meth:`synthesize` to convert text to PCM audio.

    Example::

        class MyTTSProvider:
            async def synthesize(
                self,
                text: str,
                voice: str = "default",
                style: str = "",
            ) -> bytes:
                # Your TTS logic here
                return pcm_bytes

            @property
            def is_available(self) -> bool:
                return True

            @property
            def name(self) -> str:
                return "my-tts"
    """

    async def synthesize(
        self,
        text: str,
        voice: str = "Kore",
        style: str = "",
    ) -> bytes:
        """Synthesize text to raw PCM audio bytes.

        Args:
            text: The text to speak.
            voice: Voice identifier (provider-specific).
            style: Style/audio tags to prepend (provider-specific).

        Returns:
            Raw PCM audio bytes (expected: 24 kHz, 16-bit signed, mono).
            Returns empty bytes on failure.
        """
        ...

    @property
    def is_available(self) -> bool:
        """Whether this provider is currently ready to synthesize."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name of this provider."""
        ...
