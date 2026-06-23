"""Tests for gencan_sse.config module."""

from gencan_sse.config import EngineConfig
from gencan_sse.types import VoiceMapping


class TestEngineConfigDefaults:
    """Test that EngineConfig has sensible defaults."""

    def test_zero_config(self):
        config = EngineConfig()
        assert config.tts_model == "gemini-3.1-flash-tts-preview"
        assert config.sample_rate == 24000
        assert config.sample_width == 2
        assert config.channels == 1
        assert config.volume == 0.8
        assert config.speed == 1.0
        assert config.default_voice == "Kore"
        assert config.max_queue_depth == 50
        assert config.code_block_chime is True

    def test_default_voices(self):
        config = EngineConfig()
        assert "message" in config.voices
        assert "error" in config.voices
        assert "thinking" in config.voices
        assert config.voices["message"].voice_name == "Kore"
        assert config.voices["error"].voice_name == "Fenrir"
        assert config.voices["tool_result"].enabled is False

    def test_default_fallback_models(self):
        config = EngineConfig()
        assert len(config.tts_fallback_models) >= 1


class TestEngineConfigFromDict:
    """Test EngineConfig.from_dict()."""

    def test_simple_flat_dict(self):
        config = EngineConfig.from_dict({"volume": 0.5, "speed": 1.5})
        assert config.volume == 0.5
        assert config.speed == 1.5
        # Other fields keep defaults
        assert config.sample_rate == 24000

    def test_nested_tts_dict(self):
        config = EngineConfig.from_dict({
            "tts": {
                "model": "custom-model",
            },
            "sample_rate": 16000,
        })
        assert config.tts_model == "custom-model"
        assert config.sample_rate == 16000

    def test_custom_voices(self):
        config = EngineConfig.from_dict({
            "voices": {
                "message": {
                    "voice_name": "Puck",
                    "style_prefix": "[cheerful] ",
                    "enabled": True,
                    "priority": 2,
                }
            }
        })
        assert config.voices["message"].voice_name == "Puck"
        assert config.voices["message"].style_prefix == "[cheerful] "
        # Other voices keep defaults
        assert config.voices["error"].voice_name == "Fenrir"

    def test_empty_dict(self):
        config = EngineConfig.from_dict({})
        assert config.volume == 0.8  # defaults preserved

    def test_unknown_keys_ignored(self):
        config = EngineConfig.from_dict({"unknown_key": "ignored"})
        assert config.volume == 0.8


class TestEngineConfigFromYaml:
    """Test EngineConfig.from_yaml()."""

    def test_load_from_yaml(self, tmp_yaml_config):
        config = EngineConfig.from_yaml(str(tmp_yaml_config))
        assert config.voices["message"].voice_name == "Kore"
        assert config.voices["thinking"].voice_name == "Enceladus"
        assert config.voices["tool_result"].enabled is False
        assert config.volume == 0.8

    def test_missing_file_raises(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            EngineConfig.from_yaml("/nonexistent/config.yaml")
