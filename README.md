# gencan-sse

**GenCan Speech Synthesis Engine** — A standalone, high-performance TTS pipeline and HTTP daemon with real-time priority queueing, 1000-character sentence chunking, message coalescing, circuit breaker resilience, multi-provider support (Gemini, AVFoundation, Kokoro MLX, Jonbox), and an interactive web monitoring dashboard.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Queue & Resilience Pipeline](#queue--resilience-pipeline)
  - [1000-Character Sentence Chunking](#1000-character-sentence-chunking)
  - [Queue Message Coalescing](#queue-message-coalescing)
  - [Priority Queueing](#priority-queueing)
  - [Circuit Breaker & 429 Cooldown Capping](#circuit-breaker--429-cooldown-capping)
- [TTS Providers](#tts-providers)
  - [Gemini TTS](#gemini-tts)
  - [macOS AVFoundation](#macos-avfoundation)
  - [Kokoro MLX](#kokoro-mlx)
  - [Jonbox](#jonbox)
  - [Custom Provider Protocol](#custom-provider-protocol)
- [Quick Start (Python API)](#quick-start-python-api)
- [HTTP Daemon & Web Dashboard](#http-daemon--web-dashboard)
  - [Starting the Daemon](#starting-the-daemon)
  - [Interactive Dashboard](#interactive-dashboard)
  - [REST API Endpoints](#rest-api-endpoints)
- [macOS Launchd Service Setup](#macos-launchd-service-setup)
- [Configuration Reference](#configuration-reference)
- [Environment Variables](#environment-variables)
- [License](#license)

---

## Features

- **Synchronous Non-Blocking API** — Call `engine.speak("hello")` and return immediately while audio synthesizes and plays in a background event loop thread.
- **1000-Char Sentence Chunking** — Natural punctuation-aware text splitter groups sentences up to ~1000 characters for low time-to-first-audio while enforcing hard limits.
- **Queue Message Coalescing** — Rapid sequential speak calls with identical parameters are merged in-queue (up to 3000 chars) to eliminate audio fragmentation.
- **Priority Queueing & Eviction** — Urgent items (e.g. errors) jump ahead of normal speech; stale messages are automatically evicted when queues fill.
- **Circuit Breaker & 429 Cooldown Capping** — Automatic per-model failure tracking with 429 `retryDelay` parsing, capped at 60s to prevent prolonged lockout during quota spikes.
- **Multi-Provider Architecture** — Support for Google Gemini TTS, native offline macOS AVFoundation, local Apple Silicon Kokoro MLX inference, and Jonbox/Coqui endpoints.
- **30 Supported Gemini Voices** — Full support for Google's voice catalog with per-event-type and per-IP voice routing.
- **Content Filtering** — Automatic stripping of markdown, code blocks (with optional audio chime), inline code, URLs, file paths, and horizontal rules.
- **FastAPI HTTP Daemon & Dashboard** — Built-in REST API and browser-based real-time control & monitoring dashboard.
- **macOS Launchd Service Script** — Zero-downtime background daemon installation via `setup_service.sh` for production and development.

---

## Architecture

```
                               ┌─────────────────────────────────────────────────┐
                               │           Caller / REST API / Event             │
                               └───────────────────────┬─────────────────────────┘
                                                       │
                                                       ▼
                               ┌─────────────────────────────────────────────────┐
                               │          MessageQueue & Coalescer               │
                               │  (Priority Eviction & 3000-char Merge)           │
                               └───────────────────────┬─────────────────────────┘
                                                       │
                                                       ▼
                               ┌─────────────────────────────────────────────────┐
                               │         PlaybackWorker (Background Thread)      │
                               └───────┬───────────────────────┬─────────────────┘
                                       │                       │
                                       ▼                       ▼
                         ┌───────────────────────────┐   ┌───────────────────────────┐
                         │   Classifier & Filter     │   │  Sentence Chunker (1000c) │
                         │ (Markdown, Code, URLs)    │   │  (Punctuation & Bounds)   │
                         └─────────────┬─────────────┘   └─────────────┬─────────────┘
                                       └───────────────┬───────────────┘
                                                       │
                                                       ▼
                               ┌─────────────────────────────────────────────────┐
                               │             TTSProvider Router                  │
                               │ (Circuit Breaker, 429 Capping & Fallback Chain) │
                               └───────┬───────────────┬───────────────┬─────────┘
                                       │               │               │
                                       ▼               ▼               ▼
                               ┌───────────────┐┌──────────────┐┌──────────────┐
                               │  Gemini TTS   ││ AVFoundation││  Kokoro MLX  │
                               │ (Cloud/Local) ││(macOS Native)││ (Local 82M)  │
                               └───────┬───────┘└──────┬───────┘└──────┬───────┘
                                       └───────────────┼───────────────┘
                                                       │
                                                       ▼
                               ┌─────────────────────────────────────────────────┐
                               │         AudioPlayer (24kHz 16-bit Mono)         │
                               └───────────────────────┬─────────────────────────┘
                                                       │
                                                       ▼
                                             🔊 PyAudio Playback
```

---

## Queue & Resilience Pipeline

### 1000-Character Sentence Chunking

The `chunker` module (`gencan_sse.chunker.chunk_sentences`) splits long bodies of text into natural, sentence-sized fragments using regex punctuation matching with negative lookbehinds for common abbreviations (e.g. *Mr.*, *Dr.*, *e.g.*, *etc.*).

- **Target Chunk Size**: ~1000 characters (`target_chunk_size=1000`), balancing low time-to-first-audio latency with natural acoustic cadence.
- **Minimum Length**: Short fragments (< 5 chars) are merged with adjacent sentences.
- **Max Chunk Boundary**: Over-sized sentences exceeding `max_chunk_size` (2000 chars) are safely split on word boundaries.
- **Safety Limit**: Input text exceeding 100,000 characters is automatically truncated to prevent DOS vulnerabilities.

### Queue Message Coalescing

When rapidly calling `speak()` or receiving streamed tokens, multiple small utterances can fragment audio playback. The `PlaybackWorker` automatically inspects the message queue and coalesces consecutive `SpeakMessage` objects that share matching parameters:

- **Matching Criteria**: Identical `voice`, `style`, `priority`, and `event_type`.
- **Max Coalesce Size**: Combines text up to **3000 characters** in a single synthesis payload.
- **Result**: Reduces API round-trips and provides smooth, continuous voice synthesis.

### Priority Queueing

Utterances are processed according to strict priority ordering:

| Priority Level | Value | Enum | Typical Use Case |
|---|---|---|---|
| **ERROR** | `1` | `Priority.ERROR` | System alerts & exceptions (jumps the queue) |
| **RESPONSE** | `2` | `Priority.RESPONSE` | Normal assistant messages & general speech |
| **TOOL** | `3` | `Priority.TOOL` | Tool invocation notifications (`Running read_file`) |
| **THINKING** | `4` | `Priority.THINKING` | Internal monologue & chain-of-thought |

*Note: Lower numerical values indicate higher priority. When the queue depth reaches its limit (default: 50 items), the oldest non-error message is evicted.*

### Circuit Breaker & 429 Cooldown Capping

The Gemini TTS provider implements per-model circuit breaking to maintain zero-downtime reliability:

- **Failure Threshold**: Opens after 3 consecutive API failures.
- **429 Rate Limit Parsing**: Inspects HTTP 429 response bodies for Google's `retryDelay` format (e.g., `"retryDelay": "4327s"` or `retry in 1h12m7s`).
- **Cooldown Capping**: Raw Google API retry delays can be hours long. `GeminiTTSProvider` caps all 429 cooldowns at **`max_429_cooldown` (60.0 seconds by default)**. This prevents temporary quota bursts from locking out TTS indefinitely.
- **Fallback Chain**: When a model circuit is open, synthesis cascades to configured fallback models (e.g., `gemini-2.5-flash-preview-tts` → `gemini-2.5-pro-preview-tts` → local TTS).

---

## TTS Providers

### Gemini TTS

Wraps Google's Gemini TTS API with rate limiting (default: 10 RPM), exponential backoff with jitter, and 30 supported voices:

`achernar`, `achird`, `algenib`, `algieba`, `alnilam`, `aoede`, `autonoe`, `callirrhoe`, `charon`, `despina`, `enceladus`, `erinome`, `fenrir`, `gacrux`, `iapetus`, `kore`, `laomedeia`, `leda`, `orus`, `puck`, `pulcherrima`, `rasalgethi`, `sadachbia`, `sadaltager`, `schedar`, `sulafat`, `umbriel`, `vindemiatrix`, `zephyr`, `zubenelgenubi`.

- **Default Voice**: `Kore`
- **Local Endpoint Support**: Set `GEMINI_API_BASE_URL` to route requests to a self-hosted or local proxy engine.

### macOS AVFoundation

Provides native, offline text-to-speech on macOS using Apple's `AVSpeechSynthesizer` via PyObjC.

- **Subprocess Isolation**: To avoid blocking the parent Python asyncio event loop and to service Cocoa's main run loop, synthesis runs in a lightweight dedicated subprocess.
- **Format Conversion**: Audio is captured into memory and resampled (via NumPy or linear interpolation) to 24 kHz 16-bit signed mono PCM.
- **Default Voice**: `Zoe (Premium)` (`com.apple.voice.premium.en-US.Zoe`).

### Kokoro MLX

Local Apple Silicon neural TTS using the 82M parameter `Kokoro` model via `mlx-audio`.

- **Offline Inference**: Requires `mlx-audio` installed.
- **Voice Mapping**: Automatically maps standard voice names to Kokoro IDs (e.g. `Kore` → `af_heart`, `Zephyr` → `af_alloy`, `Puck` → `am_puck`, `Charon` → `am_echo`, `Fenrir` → `am_fenrir`).

### Jonbox

Forwards synthesis requests to remote Jonbox or Coqui TTS server instances via REST API endpoints.

### Custom Provider Protocol

Implement the `TTSProvider` protocol to add custom backends:

```python
from gencan_sse import TTSProvider

class MyCustomTTS:
    @property
    def name(self) -> str:
        return "custom-tts"

    @property
    def is_available(self) -> bool:
        return True

    async def synthesize(self, text: str, voice: str = "default", style: str = "") -> tuple[bytes, dict]:
        # Return 24kHz 16-bit signed mono PCM bytes and metadata dict
        return pcm_bytes, {"model": "custom-v1"}
```

---

## Quick Start (Python API)

```python
from gencan_sse import SpeechEngine, EngineConfig

# Zero-config usage
with SpeechEngine() as engine:
    engine.speak("Hello from GenCan SSE!")
    engine.drain()  # Wait for queue playback to complete
```

### Programmatic Configuration

```python
from gencan_sse import SpeechEngine, EngineConfig

config = EngineConfig(
    volume=0.9,
    speed=1.2,
    default_voice="Puck",
    tts_model="gemini-2.5-flash-preview-tts",
    skip_code_blocks=True,
    code_block_chime=True,
)

engine = SpeechEngine(config=config)
engine.start()

# Direct text speech
engine.speak("System update complete.", voice="Aoede", priority=2)

# Process structured event JSON
engine.speak_event('{"type": "error", "message": "Connection lost"}')

engine.stop()
```

---

## HTTP Daemon & Web Dashboard

### Starting the Daemon

```bash
# Install with server dependencies
pip install -e ".[server]"

# Start daemon on default port (8765)
gencan-server

# Custom interface and port
gencan-server --host 0.0.0.0 --port 9000 --log-level debug
```

### Interactive Dashboard

Open `http://localhost:8765/dashboard` in your browser for a real-time monitoring dashboard with live queue status, activity logs, voice routing controls, volume/speed sliders, and a TTS sandbox.

### REST API Endpoints

#### Core Speech API

- **`POST /speak`** — Synthesize raw text.
  ```json
  {
    "text": "Deployment succeeded.",
    "voice": "Puck",
    "style": "[upbeat]",
    "priority": 2,
    "event_type": "message"
  }
  ```
  *Response*: `{"status": "queued", "queue_depth": 1}`

- **`POST /event`** — Process structured LLM/stream event.
  ```json
  {
    "event": {
      "type": "thinking",
      "content": "Analyzing input metrics..."
    }
  }
  ```
  *Response*: `{"status": "queued", "queue_depth": 1}`

- **`POST /control`** — Control playback engine.
  ```json
  {
    "action": "set_volume",
    "payload": {"volume": 0.75}
  }
  ```
  *Actions*: `stop`, `flush`, `set_volume`, `set_speed`, `set_voice`.

- **`GET /status`** — Basic health status.
  *Response*: `{"is_running": true, "queue_depth": 0, "tts_available": true}`

#### Monitoring & Dashboard API (`/api/*`)

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Redirects to `/dashboard` |
| `/dashboard` | `GET` | Serves the web dashboard HTML interface |
| `/api/status` | `GET` | Returns extended engine metrics, volume, speed, voices, and usage |
| `/api/providers` | `GET` | Returns list of current and available TTS providers |
| `/api/provider` | `POST` | Dynamically switches active TTS provider (`{"provider": "avfoundation"}`) |
| `/api/logs` | `GET` | Returns live activity log history |
| `/api/system-logs` | `GET` | Returns internal daemon system log buffer (last 200 entries) |
| `/api/speak` | `POST` | Dashboard sandbox speak endpoint |
| `/api/volume` | `POST` | Adjusts volume from dashboard (`{"volume": 0.8}`) |
| `/api/speed` | `POST` | Adjusts playback speed from dashboard (`{"speed": 1.0}`) |
| `/api/stop` | `POST` | Stops playback immediately |
| `/api/flush` | `POST` | Flushes queue by event type or completely |
| `/api/voice` | `POST` | Updates voice routing (`{"event_type": "message", "voice_name": "Aoede"}`) |
| `/api/service/restart` | `POST` | Restarts daemon process |
| `/api/service/stop` | `POST` | Unloads and stops launchd service |

---

## macOS Launchd Service Setup

To run `gencan-server` as a persistent background service on macOS that starts automatically on login and restarts on crash:

### Quick Setup

```bash
# Production setup (com.gencan.sse.plist)
./setup_service.sh

# Development setup (com.gencan.sse.dev.plist)
./setup_service.sh --dev
```

### Managing the Service

```bash
# Check service status
launchctl list | grep com.gencan.sse

# Unload / Stop service
launchctl unload ~/Library/LaunchAgents/com.gencan.sse.plist

# Load / Start service
launchctl load ~/Library/LaunchAgents/com.gencan.sse.plist

# Monitor logs
tail -f ~/Library/Logs/gencan-sse/service.log
tail -f ~/Library/Logs/gencan-sse/service.err
```

### Uninstalling Service

```bash
./uninstall_service.sh
```

---

## Configuration Reference

`EngineConfig` options can be set programmatically, via dictionary (`EngineConfig.from_dict()`), or loaded from a YAML file (`EngineConfig.from_yaml("config.yaml")`).

```yaml
# Example config.yaml
tts:
  model: "gemini-2.5-flash-preview-tts"
  fallback_models:
    - "gemini-2.5-pro-preview-tts"
  requests_per_minute: 10.0

audio:
  sample_rate: 24000
  volume: 0.8
  speed: 1.0

filtering:
  skip_code_blocks: true
  code_block_chime: true
  min_sentence_length: 5
  target_chunk_size: 1000

voices:
  message:
    voice_name: "Kore"
    enabled: true
  thinking:
    voice_name: "Zephyr"
    style_prefix: "[thoughtfully, inner monologue] "
    enabled: true
  error:
    voice_name: "Fenrir"
    style_prefix: "[alert] "
    enabled: true
```

### Complete Options Table

| Field | Type | Default | Description |
|---|---|---|---|
| `tts_model` | `str` | `"gemini-2.5-flash-preview-tts"` | Primary TTS model |
| `tts_fallback_models` | `list[str]` | `["gemini-2.5-flash-preview-tts", ...]` | Fallback models list |
| `tts_requests_per_minute` | `float` | `10.0` | Outbound API rate limit |
| `tts_round_robin` | `bool` | `False` | Enable round-robin model rotation |
| `sample_rate` | `int` | `24000` | Audio sample rate (Hz) |
| `sample_width` | `int` | `2` | Sample width in bytes (16-bit) |
| `channels` | `int` | `1` | Channels (1 = mono) |
| `volume` | `float` | `0.8` | Output volume (0.0 – 1.0) |
| `speed` | `float` | `1.0` | Playback speed multiplier |
| `default_voice` | `str` | `"Kore"` | Default fallback voice name |
| `max_queue_depth` | `int` | `50` | Maximum queue depth |
| `stale_timeout_seconds` | `float` | `120.0` | Stale item eviction timeout |
| `skip_code_blocks` | `bool` | `True` | Strip fenced code blocks |
| `skip_inline_code` | `bool` | `True` | Strip inline code spans |
| `skip_urls` | `bool` | `True` | Strip URL strings |
| `min_sentence_length` | `int` | `5` | Minimum sentence char length |
| `target_chunk_size` | `int` | `1000` | Target chunk character size |
| `code_block_chime` | `bool` | `True` | Play chime for skipped code blocks |

---

## Environment Variables

| Variable | Description |
|---|---|
| `AI_STUDIO_KEY` | Primary Google AI Studio API key for Gemini TTS |
| `GEMINI_API_KEY` | Secondary/Alternative Gemini API key variable |
| `GEMINI_API_BASE_URL` | Custom base URL for self-hosted/local TTS proxy |
| `GEMINI_LOCAL_MODEL` | Custom model name when using `GEMINI_API_BASE_URL` |
| `DEFAULT_VOICE_ID` | Override macOS AVFoundation default voice identifier |

---

## License

MIT © 2026 Jon Heselton
