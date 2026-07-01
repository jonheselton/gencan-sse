"""Engine configuration for gencan-sse.

Provides :class:`EngineConfig`, a pure-dataclass configuration object
with sensible defaults so that zero-config usage works out of the box::

    from gencan_sse.config import EngineConfig

    config = EngineConfig()              # all defaults
    config = EngineConfig(volume=0.5)    # override one field
    config = EngineConfig.from_yaml("my_config.yaml")

No server, hook, or integration config lives here — this module is
strictly for the standalone TTS engine.
"""

import logging
import copy
import typing
from dataclasses import dataclass, field, fields
from typing import Optional

from gencan_sse.types import VoiceMapping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default voice mappings
# ---------------------------------------------------------------------------

_DEFAULT_VOICES: dict[str, VoiceMapping] = {
    "message": VoiceMapping(
        voice_name="Kore",
        style_prefix="",
        enabled=True,
        priority=2,
    ),
    "thinking": VoiceMapping(
        voice_name="Zephyr",
        style_prefix="[thoughtfully, inner monologue] ",
        enabled=True,
        priority=4,
    ),
    "tool_use": VoiceMapping(
        voice_name="Puck",
        style_prefix="[brief, matter-of-fact] Running: ",
        enabled=True,
        priority=3,
    ),
    "tool_result": VoiceMapping(
        voice_name="Charon",
        style_prefix="[neutral, concise] ",
        enabled=False,
        priority=3,
    ),
    "error": VoiceMapping(
        voice_name="Fenrir",
        style_prefix="[alert] ",
        enabled=True,
        priority=1,
    ),
}


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    """Configuration for the GenCan Speech Synthesis Engine.

    All fields have sensible defaults.  Typical usage patterns::

        # Zero-config
        config = EngineConfig()

        # Programmatic override
        config = EngineConfig(volume=0.9, skip_code_blocks=False)

        # From a dictionary (e.g. parsed JSON / environment)
        config = EngineConfig.from_dict({"volume": 0.9})

        # From a YAML file (requires ``pyyaml``)
        config = EngineConfig.from_yaml("config.yaml")

    Attributes:
        tts_model: Primary TTS model identifier.
        tts_fallback_models: Ordered list of fallback model identifiers
            tried when the primary model is unavailable.
        tts_requests_per_minute: Rate-limit for TTS API calls.
        sample_rate: Audio sample rate in Hz.
        sample_width: Sample width in bytes (2 = 16-bit).
        channels: Number of audio channels (1 = mono).
        volume: Playback volume (0.0–1.0).
        speed: Playback speed multiplier (1.0 = normal).
        output_device: Optional name/index of the audio output device.
            ``None`` uses the system default.
        voices: Mapping of event-type name → :class:`VoiceMapping`.
        default_voice: Fallback voice name when no mapping matches.
        max_queue_depth: Maximum number of items in the audio queue.
            New items are dropped when the queue is full.
        stale_timeout_seconds: Seconds after which a queued item is
            considered stale and may be discarded.
        skip_code_blocks: Whether to skip fenced code blocks.
        skip_inline_code: Whether to skip inline ``code`` spans.
        skip_urls: Whether to strip URLs from spoken text.
        min_sentence_length: Minimum character length for a sentence
            to be worth synthesising.
        code_block_chime: Whether to play a short chime in place of
            skipped code blocks.
    """

    # -- TTS settings -------------------------------------------------------
    tts_model: str = "gemini-3.1-flash-tts-preview"
    tts_fallback_models: list[str] = field(
        default_factory=lambda: [
            "gemini-3.1-flash-tts-preview",
            "gemini-2.5-flash-preview-tts",
            "gemini-2.5-pro-preview-tts",
        ]
    )
    tts_requests_per_minute: float = 10.0
    tts_round_robin: bool = False
    jonbox_base_url: Optional[str] = None

    # -- Audio settings ------------------------------------------------------
    sample_rate: int = 24000
    sample_width: int = 2  # 16-bit
    channels: int = 1  # mono
    volume: float = 0.8
    speed: float = 1.0
    output_device: Optional[str] = None

    # -- Voice routing -------------------------------------------------------
    voices: dict[str, VoiceMapping] = field(
        default_factory=lambda: copy.deepcopy(_DEFAULT_VOICES)
    )
    default_voice: str = "Kore"

    # -- IP Voice routing ----------------------------------------------------
    premium_voice_pool: list[str] = field(
        default_factory=lambda: ['aoede', 'callirrhoe', 'charon', 'fenrir']
    )
    ip_voice_timeout_hours: float = 2.0

    # -- Queue settings ------------------------------------------------------
    max_queue_depth: int = 50
    stale_timeout_seconds: float = 120.0

    # -- Filtering -----------------------------------------------------------
    skip_code_blocks: bool = True
    skip_inline_code: bool = True
    skip_urls: bool = True
    min_sentence_length: int = 5
    target_chunk_size: int = 250
    code_block_chime: bool = True

    # -- Class methods -------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "EngineConfig":
        """Create a config from a dictionary, using defaults for missing keys.

        Supports both flat dictionaries and nested structures.  For nested
        dicts whose top-level key is ``"tts"``, sub-keys are flattened with
        a ``tts_`` prefix (e.g. ``{"tts": {"model": "x"}}`` →
        ``tts_model="x"``).

        Voice entries under ``"voices"`` are merged with the built-in
        defaults so callers only need to specify overrides.

        Args:
            data: Configuration dictionary.

        Returns:
            A fully-populated :class:`EngineConfig`.
        """
        # --- Parse voice overrides ------------------------------------------
        voices: dict[str, VoiceMapping] = copy.deepcopy(_DEFAULT_VOICES)
        if "voices" in data:
            if isinstance(data["voices"], dict):
                for name, vdata in data["voices"].items():
                    if isinstance(vdata, dict):
                        default = _DEFAULT_VOICES.get(name)
                        voices[name] = VoiceMapping(
                            voice_name=vdata.get(
                                "voice_name",
                                default.voice_name if default else "Kore",
                            ),
                            style_prefix=vdata.get(
                                "style_prefix",
                                default.style_prefix if default else "",
                            ),
                            enabled=bool(vdata.get(
                                "enabled",
                                default.enabled if default else True,
                            )),
                            priority=int(vdata.get(
                                "priority",
                                default.priority if default else 2,
                            )),
                        )
            else:
                logger.warning("'voices' section in config must be a dictionary, ignoring.")

        # --- Flatten nested sections ----------------------------------------
        flat: dict[str, object] = {}
        known_sections = ("tts", "audio", "queue", "filtering")
        for key, value in data.items():
            if key == "voices":
                continue
            if isinstance(value, dict) and key in known_sections:
                for subkey, subvalue in value.items():
                    # Prefix sub-keys for known namespaced sections
                    flat_key = (
                        f"{key}_{subkey}" if key == "tts" else subkey
                    )
                    flat[flat_key] = subvalue
            else:
                flat[key] = value

        # --- Map to dataclass fields and apply coercion/validation ---------
        field_types = {f.name: f.type for f in fields(cls)}
        kwargs: dict[str, object] = {"voices": voices}
        for key, value in flat.items():
            if key in field_types:
                expected_type = field_types[key]
                origin = typing.get_origin(expected_type) or expected_type
                is_optional = False
                if origin is typing.Union:
                    is_optional = type(None) in typing.get_args(expected_type)
                
                if value is None:
                    if is_optional:
                        kwargs[key] = None
                        continue
                    else:
                        logger.warning("Key '%s' cannot be None. Falling back to default.", key)
                        continue

                # Get core target type
                if origin is typing.Union:
                    union_args = typing.get_args(expected_type)
                    actual_types = [t for t in union_args if t is not type(None)]
                    if actual_types:
                        target_type = actual_types[0]
                        target_origin = typing.get_origin(target_type) or target_type
                    else:
                        target_type = str
                        target_origin = str
                else:
                    target_type = expected_type
                    target_origin = origin

                # Core Coercion
                if target_origin is list:
                    if isinstance(value, list):
                        kwargs[key] = value
                    else:
                        logger.warning("Type mismatch for key '%s': expected list, got %s. Falling back to default.", key, type(value).__name__)
                elif target_origin is bool:
                    if isinstance(value, str):
                        kwargs[key] = value.lower() in ("true", "1", "yes")
                    else:
                        kwargs[key] = bool(value)
                elif target_origin is int:
                    try:
                        kwargs[key] = int(value)
                    except (ValueError, TypeError):
                        logger.warning("Type mismatch for key '%s': expected int, got %s. Falling back to default.", key, type(value).__name__)
                elif target_origin is float:
                    try:
                        kwargs[key] = float(value)
                    except (ValueError, TypeError):
                        logger.warning("Type mismatch for key '%s': expected float, got %s. Falling back to default.", key, type(value).__name__)
                elif target_origin is str:
                    kwargs[key] = str(value)
                else:
                    if isinstance(value, target_origin):
                        kwargs[key] = value
                    else:
                        logger.warning("Type mismatch for key '%s': expected %s, got %s. Falling back to default.", key, target_origin.__name__, type(value).__name__)
            else:
                logger.debug("Ignoring unknown config key: %s", key)

        return cls(**kwargs)  # type: ignore[arg-type]

    @classmethod
    def from_yaml(cls, path: str) -> "EngineConfig":
        """Load configuration from a YAML file.

        Requires ``pyyaml`` to be installed.  Missing keys use defaults.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            :class:`EngineConfig` with values from YAML merged with defaults.

        Raises:
            ImportError: If ``pyyaml`` is not installed.
            FileNotFoundError: If *path* does not exist.
        """
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "pyyaml is required to load YAML config files. "
                "Install with: pip install pyyaml"
            )

        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            logger.warning(
                "Config file %s does not contain a mapping; using defaults.",
                path,
            )
            return cls()

        return cls.from_dict(raw)
