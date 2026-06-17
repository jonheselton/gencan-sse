"""Shared pytest fixtures for gencan_sse tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_pyaudio():
    """Patch pyaudio.PyAudio with a MagicMock.

    Yields the mock *instance* so tests can assert on open(), write(), etc.
    """
    with patch("pyaudio.PyAudio") as mock_pa:
        instance = MagicMock()
        mock_pa.return_value = instance
        yield instance


@pytest.fixture
def mock_genai_client():
    """Patch google.genai.Client with a MagicMock.

    Yields the mock *instance* so tests can configure return values
    for models.generate_content(), etc.
    """
    with patch("google.genai.Client") as mock_client:
        instance = MagicMock()
        mock_client.return_value = instance
        yield instance


@pytest.fixture
def sample_events() -> list[dict]:
    """Return a list of sample JSONL event dicts for testing.

    Covers all major event types: message, tool_use, tool_result,
    error, thinking, init, and result.
    """
    return [
        {"type": "message", "content": "Hello, world!"},
        {"type": "tool_use", "tool": "read_file", "args": {"path": "/tmp/test.py"}},
        {"type": "tool_result", "tool": "read_file", "output": "print('hello')"},
        {"type": "error", "message": "Something went wrong"},
        {"type": "thinking", "content": "Let me consider this..."},
        {"type": "init", "session_id": "abc123", "model": "gemini-2.5-pro"},
        {"type": "result", "summary": "Task completed", "tokens": 42},
    ]


@pytest.fixture
def tmp_yaml_config(tmp_path: Path) -> Path:
    """Create a temporary voices.yaml config file with valid content.

    Returns the Path to the created YAML file.
    """
    config_content = """\
tts:
  model: gemini-3.1-flash-tts-preview
  sample_rate: 24000
  sample_width: 2
  channels: 1

voices:
  message:
    voice_name: Kore
    style_prefix: ""
    enabled: true
    priority: 2
  thinking:
    voice_name: Enceladus
    style_prefix: "[thoughtfully] "
    enabled: true
    priority: 4
  tool_use:
    voice_name: Puck
    style_prefix: "[brief] Running: "
    enabled: true
    priority: 3
  tool_result:
    voice_name: Charon
    style_prefix: "[neutral] "
    enabled: false
    priority: 3
  error:
    voice_name: Fenrir
    style_prefix: "[alert] "
    enabled: true
    priority: 1

filtering:
  skip_code_blocks: true
  skip_inline_code: true
  skip_urls: true
  min_sentence_length: 5
  max_queue_depth: 5
  stale_timeout_seconds: 10

audio:
  volume: 0.8
  code_block_chime: true
"""
    config_file = tmp_path / "voices.yaml"
    config_file.write_text(config_content)
    return config_file
