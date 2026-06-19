# gencan-sse — Caller Integration Guide

> **For developers integrating GenCan Speech Synthesis Engine into screen readers, CLI tools, or other applications.**

---

## 1. Environment Setup

### Required
```bash
# Set your Gemini API key (one of these)
export AI_STUDIO_KEY="your-api-key-here"
# or
export GEMINI_API_KEY="your-api-key-here"
```

### Installation
```bash
# From the repo
cd /Users/jonheselton/Projects/gencan-sse
pip install -e ".[gemini]"

# Or with all optional deps
pip install -e ".[all]"
```

### Verify Installation
```python
from gencan_sse import SpeechEngine
engine = SpeechEngine()
print(engine.status())
# Should show: tts_available=True (if API key is set)
```

---

## 2. Minimal Usage (5 Lines)

```python
from gencan_sse import SpeechEngine

engine = SpeechEngine()
engine.start()
engine.speak("Hello from your screen reader!")
# ... your app does other things ...
engine.stop()
```

**Or with context manager** (auto start/stop):
```python
from gencan_sse import SpeechEngine

with SpeechEngine() as engine:
    engine.speak("Hello!")
    engine.speak("This plays after the first utterance.")
    import time; time.sleep(10)  # wait for playback
```

---

## 3. Complete API Contract

### `SpeechEngine(config=None, tts_provider=None)`

**Constructor.** Creates a new engine instance. Does NOT start it.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config` | `EngineConfig \| None` | `None` | Engine configuration. Uses sensible defaults if `None`. |
| `tts_provider` | `TTSProvider \| None` | `None` | Custom TTS backend. Uses Gemini if `None`. |

---

### `engine.start() → None`

**Start the engine.** Launches a background daemon thread that handles TTS synthesis and audio playback. **Must be called before `speak()`.**

- Safe to call multiple times (no-op if already running)
- The background thread is a daemon — it won't prevent your program from exiting

---

### `engine.speak(text, voice=None, style="", priority=Priority.RESPONSE, event_type=EventType.MESSAGE) → SpeakResult`

**The main method. Speak text aloud.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | `str` | *(required)* | The text to speak |
| `voice` | `str \| None` | `None` (uses default) | Voice name: `"Kore"`, `"Puck"`, `"Fenrir"`, `"Zephyr"`, `"Charon"`, `"Aoede"`, etc. |
| `style` | `str` | `""` | Style prefix prepended to text, e.g. `"[alert] "`, `"[whisper] "` |
| `priority` | `Priority` | `Priority.RESPONSE` | Queue priority. Lower number = plays sooner. |
| `event_type` | `EventType` | `EventType.MESSAGE` | Event category (for logging/routing) |

**Returns:** `SpeakResult`

```python
@dataclass
class SpeakResult:
    status: str      # "queued" | "skipped" | "error"
    message: str     # Human-readable detail
    queue_depth: int  # Queue size after this call
```

**Behavior:**
- **Returns immediately** — does NOT block until audio finishes
- Text is queued internally and played sequentially (no clipping/overlap)
- Empty or whitespace-only text returns `status="skipped"`
- If engine is not started, returns `status="error"`

**Example:**
```python
result = engine.speak("Alert! Something happened.", voice="Fenrir", style="[urgent] ")
if result.status == "queued":
    print(f"Queued, {result.queue_depth} items in queue")
```

---

### `engine.speak_event(event_json) → SpeakResult`

**Process a structured JSON event** through the full pipeline (classify → filter → voice route → TTS → play).

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_json` | `str` | JSON string with `"type"` and content fields |

**Supported event types:**

| `type` | Content field | Voice (default) | Priority |
|--------|--------------|-----------------|----------|
| `"message"` | `"content"` | Kore | RESPONSE (2) |
| `"thinking"` | `"content"` | Zephyr | THINKING (4) |
| `"tool_use"` | `"tool"` → "Running {tool}" | Puck | TOOL (3) |
| `"tool_result"` | `"output"` | Charon | TOOL (3) |
| `"error"` | `"message"` | Fenrir | ERROR (1) |
| `"init"` | — | — | *skipped* |
| `"result"` | — | — | *skipped* |

**Example:**
```python
import json
engine.speak_event(json.dumps({
    "type": "error",
    "message": "File not found"
}))
```

---

### `engine.set_volume(volume) → None`

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `volume` | `float` | 0.0 – 1.0 | Playback volume. Clamped to range. |

---

### `engine.set_speed(speed) → None`

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `speed` | `float` | 0.5 – 2.0 | Playback speed multiplier. Clamped to range. |

---

### `engine.set_voice(event_type, voice_name) → None`

Change the voice used for a specific event type at runtime.

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | `"message"`, `"error"`, `"thinking"`, `"tool_use"`, `"tool_result"` |
| `voice_name` | `str` | Any Gemini voice name |

---

### `engine.flush_queue(event_type="") → None`

Clear the audio playback queue.

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | Event type to flush, or `""` to flush all |

---

### `engine.stop_audio() → None`

Stop current playback and clear the queue immediately.

---

### `engine.drain(timeout=None) → None`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout` | `float \| None` | `None` | Max seconds to wait. `None` = wait indefinitely. |

Block until audio queue is empty or timeout expires.

---

### `engine.stop() → None`

**Shut down the engine.** Stops the background thread and releases PyAudio resources. Waits up to 5 seconds for graceful shutdown.

---

### `engine.status() → EngineStatus`

Returns current engine state:

```python
@dataclass
class EngineStatus:
    is_running: bool        # Whether the engine is active
    queue_depth: int        # Audio chunks waiting for playback
    volume: float           # Current volume (0.0–1.0)
    speed: float            # Current speed multiplier
    uptime_seconds: float   # Time since start()
    tts_provider: str       # Name of active TTS provider
    tts_available: bool     # Whether TTS API is reachable
    voices: dict            # Event type → voice name mapping
```

---

### `engine.is_running → bool` (property)

Whether the engine is currently running.

---

## 4. Priority System

Items are played in priority order. Lower number = higher priority.

| Priority | Value | Use Case |
|----------|-------|----------|
| `Priority.ERROR` | 1 | Errors, alerts — jumps the queue |
| `Priority.RESPONSE` | 2 | Normal speech, messages |
| `Priority.TOOL` | 3 | Tool use/result notifications |
| `Priority.THINKING` | 4 | Thinking/reasoning (lowest priority) |

```python
from gencan_sse import Priority

# This error will play before any queued normal messages
engine.speak("Critical error!", priority=Priority.ERROR)
```

---

## 5. Available Voices (Gemini TTS)

| Voice | Character | Good For |
|-------|-----------|----------|
| `Kore` | Clear, neutral female | Default messages |
| `Aoede` | Warm, expressive female | Narrative content |
| `Puck` | Bright, energetic | Notifications, tool output |
| `Zephyr` | Soft, contemplative | Thinking, inner monologue |
| `Charon` | Deep, measured | Status reports |
| `Fenrir` | Authoritative, alert | Errors, warnings |
| `Enceladus` | Thoughtful male | Alternative thinking voice |

Style prefixes influence delivery:
```python
engine.speak("Danger!", voice="Fenrir", style="[urgent, alarmed] ")
engine.speak("Let me think...", voice="Zephyr", style="[thoughtfully, inner monologue] ")
engine.speak("File saved.", voice="Puck", style="[brief, matter-of-fact] ")
```

---

## 6. Configuration

### Zero-config (works out of the box)
```python
engine = SpeechEngine()
```

### Programmatic
```python
from gencan_sse import SpeechEngine, EngineConfig

config = EngineConfig(
    volume=0.9,
    speed=1.2,
    default_voice="Aoede",
    max_queue_depth=10,
    stale_timeout_seconds=15.0,
)
engine = SpeechEngine(config=config)
```

### From YAML
```python
config = EngineConfig.from_yaml("/path/to/config.yaml")
engine = SpeechEngine(config=config)
```

### From dict
```python
config = EngineConfig.from_dict({
    "volume": 0.9,
    "speed": 1.0,
    "default_voice": "Kore",
})
engine = SpeechEngine(config=config)
```

### All config fields and defaults:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tts_model` | `str` | `"gemini-3.1-flash-tts-preview"` | Primary TTS model |
| `tts_fallback_models` | `list[str]` | `["gemini-2.5-flash-preview-tts", ...]` | Fallback models |
| `tts_requests_per_minute` | `float` | `10.0` | API rate limit |
| `sample_rate` | `int` | `24000` | Audio sample rate (Hz) |
| `sample_width` | `int` | `2` | Sample width (bytes, 2=16-bit) |
| `channels` | `int` | `1` | Audio channels (1=mono) |
| `volume` | `float` | `0.8` | Playback volume (0.0–1.0) |
| `speed` | `float` | `1.0` | Playback speed multiplier |
| `output_device` | `str \| None` | `None` | PyAudio device name (None=system default) |
| `default_voice` | `str` | `"Kore"` | Default voice for speak() |
| `max_queue_depth` | `int` | `5` | Max items in audio queue |
| `stale_timeout_seconds` | `float` | `10.0` | Evict queue items older than this |
| `code_block_chime` | `bool` | `True` | Play a tone when code blocks are detected |

---

## 7. Custom TTS Provider

To use a different TTS backend (macOS `say`, local model, OpenAI, etc.):

```python
from gencan_sse import SpeechEngine, TTSProvider

class MacOSSayProvider:
    """Use macOS built-in 'say' command for TTS."""
    
    async def synthesize(self, text: str, voice: str = "default", style: str = "") -> bytes:
        import subprocess, struct
        # Use macOS say to generate AIFF, convert to raw PCM
        proc = subprocess.run(
            ["say", "-v", voice, "-o", "/tmp/tts.aiff", text],
            capture_output=True
        )
        # ... convert AIFF to PCM bytes ...
        return pcm_bytes  # Must be: 24kHz, 16-bit signed, mono
    
    @property
    def is_available(self) -> bool:
        return True
    
    @property
    def name(self) -> str:
        return "macos-say"

engine = SpeechEngine(tts_provider=MacOSSayProvider())
```

### TTSProvider Protocol Requirements

Your provider class must implement:

| Method/Property | Signature | Returns |
|----------------|-----------|---------|
| `synthesize()` | `async (text: str, voice: str, style: str) → bytes` | Raw PCM: 24kHz, 16-bit signed LE, mono |
| `is_available` | `@property → bool` | Whether provider is ready |
| `name` | `@property → str` | Human-readable name |

**Audio format:** Raw PCM bytes, 24000 Hz sample rate, 16-bit signed little-endian, mono. No WAV header.

---

## 8. Threading & Concurrency Guarantees

- **`speak()` is thread-safe** — call it from any thread
- **`speak()` never blocks** — returns immediately after queuing
- **Audio plays sequentially** — no clipping or overlapping
- **Priority ordering** — errors play before normal messages
- **Background thread is a daemon** — won't prevent program exit
- **`stop()` is safe** — waits up to 5s for graceful shutdown
- **Multiple engines allowed** — each has its own thread and queue

---

## 9. Screen Reader Integration Example

```python
#!/usr/bin/env python3
"""Example: Screen reader integration with gencan-sse."""

import time
from gencan_sse import SpeechEngine, EngineConfig, Priority

# Configure for screen reader use
config = EngineConfig(
    volume=0.9,
    speed=1.3,            # Slightly faster for screen reading
    default_voice="Kore",
    max_queue_depth=20,   # Larger queue for rapid text
    stale_timeout_seconds=30.0,
)

engine = SpeechEngine(config=config)
engine.start()

# Simulate screen reader feeding text to the engine
paragraphs = [
    "Welcome to the application.",
    "You have 3 unread notifications.",
    "Press Enter to continue, or Tab to navigate.",
]

for text in paragraphs:
    engine.speak(text)

# Interrupt with high-priority alert
engine.speak(
    "Warning: battery low, 10 percent remaining.",
    voice="Fenrir",
    style="[alert] ",
    priority=Priority.ERROR,
)

# Wait for all audio to finish
time.sleep(20)
engine.stop()
```

---

## 9.5 HTTP API Integration

For non-Python projects, gencan-sse provides a REST API via a FastAPI daemon:

```bash
# Start the server
gencan-server --port 8765
```

The server exposes two main endpoints:

- **`POST /speak`** — Direct speech. You control the voice, style, and priority.
- **`POST /event`** — Structured events. The server handles classification, voice routing, and filtering.

See [API_REFERENCE.md](API_REFERENCE.md) for complete endpoint documentation with schemas and examples.

### When to use `/speak` vs `/event`

| Use Case | Endpoint | Why |
|----------|----------|-----|
| MCP tool / screen reader | `/speak` | You already know the text, voice, and priority |
| Piping LLM stream output | `/event` | Let the server classify, filter, and route voices |
| Notification system | `/speak` | Direct control over delivery |
| Gemini CLI integration | `/event` | Handles all event types automatically |

---

## 10. Error Handling

The engine is designed to **never crash the caller**:

- If TTS API fails → plays a short noise fallback
- If API key is missing → logs a warning, returns empty audio
- If all TTS models fail → circuit breaker opens, skips silently
- If `speak()` is called before `start()` → returns `SpeakResult(status="error")`
- If text is empty → returns `SpeakResult(status="skipped")`

Check `result.status` if you need to know what happened:
```python
result = engine.speak("hello")
if result.status == "error":
    print(f"Engine error: {result.message}")
elif result.status == "skipped":
    print("Text was skipped (empty or filtered)")
elif result.status == "queued":
    print(f"Playing! Queue depth: {result.queue_depth}")
```
