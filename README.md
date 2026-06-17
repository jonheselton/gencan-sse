# gencan-sse

**GenCan Speech Synthesis Engine** — a standalone, reusable TTS pipeline with a synchronous API, internal message queue, and pluggable TTS providers.

## Features

- **Synchronous API** — call `engine.speak("hello")` and it returns immediately. Audio plays in the background.
- **Internal message queue** — multiple callers can submit text without clipping or overlapping. Utterances play sequentially.
- **Priority queue** — errors jump ahead of normal messages. Stale entries are evicted automatically.
- **Pluggable TTS providers** — ships with Gemini TTS. Implement the `TTSProvider` protocol to add any backend.
- **Content filtering** — strips markdown, code blocks, URLs, and file paths for clean speech output.
- **Voice routing** — different voices for different event types (messages, errors, thinking, tool use).
- **Zero-config defaults** — works out of the box with sensible defaults. Customize via code or YAML.

## Quick Start

```python
from gencan_sse import SpeechEngine

engine = SpeechEngine()
engine.start()
engine.speak("Hello from GenCan!")
engine.stop()
```

Or use the context manager:

```python
from gencan_sse import SpeechEngine

with SpeechEngine() as engine:
    engine.speak("Hello from GenCan!")
```

## Installation

```bash
# Clone the repo
git clone https://github.com/jonheselton/gencan-sse.git
cd gencan-sse

# Install with Gemini TTS support
pip install -e ".[gemini]"

# Install with all optional dependencies
pip install -e ".[all]"

# Install for development
pip install -e ".[dev]"
```

### Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `pyaudio` | Yes | Local audio playback |
| `google-genai` | Optional | Gemini TTS API |
| `python-dotenv` | Optional | `.env` file support |
| `pyyaml` | Optional | YAML config file loading |

## Configuration

### Zero-config (defaults)

```python
engine = SpeechEngine()  # Uses all defaults
```

### Programmatic config

```python
from gencan_sse import SpeechEngine, EngineConfig

config = EngineConfig(
    volume=0.9,
    speed=1.2,
    default_voice="Puck",
    tts_model="gemini-2.5-flash-preview-tts",
)
engine = SpeechEngine(config=config)
```

### YAML config

```python
from gencan_sse import SpeechEngine, EngineConfig

config = EngineConfig.from_yaml("config.yaml")
engine = SpeechEngine(config=config)
```

## Custom TTS Provider

Implement the `TTSProvider` protocol to use any TTS backend:

```python
from gencan_sse import SpeechEngine, TTSProvider

class MyLocalTTS:
    """Example custom TTS provider."""
    
    async def synthesize(self, text: str, voice: str = "default", style: str = "") -> bytes:
        # Your TTS logic here — return raw PCM bytes (24kHz, 16-bit, mono)
        return pcm_bytes
    
    @property
    def is_available(self) -> bool:
        return True
    
    @property
    def name(self) -> str:
        return "my-local-tts"

engine = SpeechEngine(tts_provider=MyLocalTTS())
engine.start()
engine.speak("Using my custom TTS!")
engine.stop()
```

## API Reference

### `SpeechEngine`

| Method | Description |
|--------|-------------|
| `start()` | Start the engine (launches background thread) |
| `stop()` | Stop the engine and release resources |
| `speak(text, voice, style, priority)` | Speak text (returns immediately, plays in background) |
| `speak_event(event_json)` | Process a structured JSON event through the full pipeline |
| `set_volume(volume)` | Set volume (0.0 to 1.0) |
| `set_speed(speed)` | Set playback speed (0.5 to 2.0) |
| `set_voice(event_type, voice_name)` | Change voice for an event type |
| `flush_queue(event_type)` | Clear the audio queue |
| `stop_audio()` | Stop playback and clear queue |
| `status()` | Get engine status (running, queue depth, volume, etc.) |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AI_STUDIO_KEY` | Google AI Studio API key (for Gemini TTS) |
| `GEMINI_API_KEY` | Alternative API key variable |
| `GEMINI_API_BASE_URL` | Custom API base URL (for local/self-hosted TTS) |

## Architecture

```
Caller (sync)  ──►  MessageQueue  ──►  PlaybackWorker (async thread)
                                            │
                                     ┌──────┼──────┐
                                     ▼      ▼      ▼
                                Classify  Filter  Chunk
                                            │
                                            ▼
                                     TTSProvider.synthesize()
                                            │
                                            ▼
                                     AudioPlayer.enqueue()
                                            │
                                            ▼
                                     PyAudio playback
```

## Relationship to ag-voice

gencan-sse was extracted from [ag-voice](https://github.com/jonheselton/ag-voice), a TTS sidecar for Antigravity AI agents. The engine modules (classifier, chunker, filters, audio player, TTS client) were decoupled from the MCP server layer and wrapped in a standalone `SpeechEngine` facade.

ag-voice will be updated in a future PR to use gencan-sse as its engine, making `mcp_server.py` a thin adapter.

## License

MIT © 2026 Jon Heselton
