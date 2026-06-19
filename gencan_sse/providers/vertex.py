"""Vertex AI TTS provider for gencan-sse.

Uses the Gemini API via google-genai but routes through Vertex AI
for self-hosted model usage. Inherits resilience features from GeminiTTSProvider.
"""

import logging
import os
from google import genai

from gencan_sse.providers.gemini import GeminiTTSProvider

logger = logging.getLogger(__name__)


class VertexTTSProvider(GeminiTTSProvider):
    """Vertex AI wrapper for TTS."""

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        **kwargs
    ) -> None:
        """Initialise Vertex AI provider."""
        super().__init__(**kwargs)
        
        self._client = None
        self._local_client = None
        
        self.project = project or os.environ.get("VERTEX_PROJECT")
        self.location = location or os.environ.get("VERTEX_LOCATION", "us-central1")
        
        try:
            self._client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location
            )
            logger.info(
                "VertexTTSProvider initialized — project: %s, location: %s",
                self.project,
                self.location
            )
        except ImportError:
            logger.warning("google-genai package not installed. Vertex TTS disabled.")
        except Exception as exc:
            logger.warning("Failed to initialize Vertex TTS client: %s", exc)

    @property
    def name(self) -> str:
        return "vertex_ai"
