# gencan-sse — REST API Reference

> **For developers integrating with the gencan-sse HTTP daemon from any language.**

---

## Overview

gencan-sse can run as a standalone HTTP daemon, exposing a REST API for language-agnostic TTS integration. The server is built on [FastAPI](https://fastapi.tiangolo.com/) and provides four endpoints for speech synthesis, event processing, playback control, and status monitoring.

When running, interactive API docs are available at `http://localhost:8765/docs` (Swagger UI) and `http://localhost:8765/redoc` (ReDoc).

---

## Quick Start

### Install & Run

```bash
# Install with server support
pip install -e ".[server]"

# Start the daemon (default: http://127.0.0.1:8765)
gencan-server

# Custom host/port
gencan-server --host 0.0.0.0 --port 9000

# With debug logging
gencan-server --log-level debug
```

### First Request

```bash
curl -X POST http://localhost:8765/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from the REST API!"}'
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AI_STUDIO_KEY` | Yes* | Google AI Studio API key for Gemini TTS |
| `GEMINI_API_KEY` | Yes* | Alternative API key variable |
| `GEMINI_API_BASE_URL` | No | Custom base URL for local/self-hosted TTS |

\* At least one API key is required for speech synthesis. Without it, the engine runs in silent mode.

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Interface to bind to |
| `--port` | `8765` | Port to bind to |
| `--log-level` | `info` | Logging level (`debug`, `info`, `warning`, `error`, `critical`) |

---

## `speak` vs `event` — When to Use Which

The server provides two paths for producing speech, designed for different integration patterns:

```
POST /speak — Direct Control
─────────────────────────────────────────────────
Input: raw text + voice + style + priority
  └─► Chunker ─► TTS Provider ─► AudioPlayer ─► 🔊

POST /event — Automatic Pipeline
─────────────────────────────────────────────────
Input: structured JSON event
  └─► Classifier ─► Voice Router ─► Filter ─► Chunker ─► TTS Provider ─► AudioPlayer ─► 🔊
```

| | `POST /speak` | `POST /event` |
|---|---|---|
| **Input** | Raw text + explicit voice/style/priority | Structured JSON with `type` field |
| **Voice selection** | Caller decides | Auto-routed by event type |
| **Content filtering** | None — speaks exactly what you send | Strips markdown, code blocks, URLs, file paths |
| **Classification** | None | Automatic event type detection |
| **Best for** | MCP tools, screen readers, notification systems | Piping raw LLM output, Gemini CLI stream-json |

### Decision Guide

| Use Case | Endpoint | Why |
|----------|----------|-----|
| MCP tool speaking to user | `/speak` | You already know the text, voice, and priority |
| Piping Gemini CLI output | `/event` | Automatic voice routing + content filtering |
| Screen reader integration | `/speak` | Direct control over delivery |
| Error alert system | `/speak` | Use `priority: 1` to jump the queue |
| Chat UI reading responses aloud | `/event` | Handles thinking, tool use, errors automatically |

---

## Endpoints

### `POST /speak` — Speak Raw Text

Synthesize and speak text directly. Returns immediately; audio plays in the background.

#### Request Body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | `string` | **Yes** | — | The text to synthesize and speak |
| `voice` | `string` | No | `null` (uses engine default `"Kore"`) | Voice name (see [Voices](#voices) table) |
| `style` | `string` | No | `""` | Style prefix prepended before synthesis (e.g. `"[alert] "`, `"[whisper] "`) |
| `priority` | `integer` | No | `2` | Queue priority — lower = higher priority (see [Priority](#priority-levels) table) |
| `event_type` | `string` | No | `"message"` | Event classification for logging/routing (see [EventType](#event-types) table) |

#### Response

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"queued"`, `"skipped"`, or `"error"` |
| `queue_depth` | `integer` | Number of items in the audio queue after this call |

#### Example

```bash
curl -X POST http://localhost:8765/speak \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Warning: disk usage is at 95 percent.",
    "voice": "Fenrir",
    "style": "[urgent, alarmed] ",
    "priority": 1,
    "event_type": "error"
  }'
```

```json
{"status": "queued", "queue_depth": 1}
```

#### Behavior Notes

- Returns immediately — does NOT block until audio finishes playing.
- Empty or whitespace-only text returns `status: "skipped"`.
- Text is chunked into sentences for faster time-to-first-audio.
- No content filtering is applied — the text is spoken exactly as provided.

---

### `POST /event` — Process a Structured Event

Process a structured JSON event through the full pipeline: classify → voice route → filter → chunk → synthesize → play.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event` | `object` | **Yes** | A JSON object with a `type` field and content fields |

#### Supported Event Types

| `type` | Content Field | Extracted Text | Default Voice | Priority |
|--------|--------------|----------------|---------------|----------|
| `"message"` | `content` | The content value | Kore | RESPONSE (2) |
| `"thinking"` | `content` | The content value | Zephyr | THINKING (4) |
| `"tool_use"` | `tool` | `"Running {tool}"` | Puck | TOOL (3) |
| `"tool_result"` | `output` | The output value | Charon | TOOL (3) |
| `"error"` | `message` | The message value | Fenrir | ERROR (1) |
| `"init"` | — | — | — | *Skipped* |
| `"result"` | — | — | — | *Skipped* |

#### Response

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"queued"`, `"skipped"`, or `"error"` |
| `queue_depth` | `integer` | Number of items in the audio queue |

#### Examples

**Message event:**
```bash
curl -X POST http://localhost:8765/event \
  -H "Content-Type: application/json" \
  -d '{"event": {"type": "message", "content": "Here is your **analysis** of the `config.py` file."}}'
```
→ Speaks "Here is your analysis of the config.py file." in Kore voice (markdown stripped).

**Error event:**
```bash
curl -X POST http://localhost:8765/event \
  -H "Content-Type: application/json" \
  -d '{"event": {"type": "error", "message": "FileNotFoundError: config.yaml not found"}}'
```
→ Speaks "FileNotFoundError: config.yaml not found" in Fenrir voice with ERROR priority (jumps queue).

**Tool use event:**
```bash
curl -X POST http://localhost:8765/event \
  -H "Content-Type: application/json" \
  -d '{"event": {"type": "tool_use", "tool": "read_file", "args": {"path": "/tmp/data.json"}}}'
```
→ Speaks "Running read_file" in Puck voice.

**Thinking event:**
```bash
curl -X POST http://localhost:8765/event \
  -H "Content-Type: application/json" \
  -d '{"event": {"type": "thinking", "content": "Let me analyze the error traceback..."}}'
```
→ Speaks "Let me analyze the error traceback..." in Zephyr voice with `[thoughtfully, inner monologue]` style prefix.

#### Content Filtering

The `/event` pipeline automatically applies these filters before synthesis:

1. **Markdown stripping** — Removes `###` headings, `**bold**`, `*italic*`, `> blockquotes`, bullet prefixes
2. **Code block skipping** — Detects ` ``` ` fences and skips code content (plays a chime instead)
3. **Inline code unwrapping** — `` `variable` `` → `variable`
4. **URL replacement** — `https://example.com/path` → "a URL"
5. **File path replacement** — `/Users/jon/file.py` → "a file path"
6. **Deduplication** — Skips text identical to the last 5 utterances
7. **Horizontal rule skipping** — `---`, `***`, `___` are silently dropped

---

### `POST /control` — Control the Audio Player

Send control actions to the engine (volume, speed, flush, stop, voice changes).

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | `string` | **Yes** | The control action to perform (see table below) |
| `payload` | `object` | No | Action-specific parameters (default: `{}`) |

#### Control Actions

| Action | Payload | Description |
|--------|---------|-------------|
| `"stop"` | None | Stop current playback and clear the queue |
| `"flush"` | `{"event_type": "thinking"}` | Clear queued items of a specific type, or all if empty string |
| `"set_volume"` | `{"volume": 0.5}` | Set volume (0.0 to 1.0) |
| `"set_speed"` | `{"speed": 1.5}` | Set playback speed (0.5 to 2.0) |
| `"set_voice"` | `{"event_type": "message", "voice_name": "Aoede"}` | Change voice for an event type |

#### Response

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"ok"` on success |
| `action` | `string` | The action that was performed |

#### Examples

```bash
# Set volume to 50%
curl -X POST http://localhost:8765/control \
  -H "Content-Type: application/json" \
  -d '{"action": "set_volume", "payload": {"volume": 0.5}}'

# Speed up playback to 1.5x
curl -X POST http://localhost:8765/control \
  -H "Content-Type: application/json" \
  -d '{"action": "set_speed", "payload": {"speed": 1.5}}'

# Stop all audio immediately
curl -X POST http://localhost:8765/control \
  -H "Content-Type: application/json" \
  -d '{"action": "stop"}'

# Flush only thinking events from the queue
curl -X POST http://localhost:8765/control \
  -H "Content-Type: application/json" \
  -d '{"action": "flush", "payload": {"event_type": "thinking"}}'

# Change the error voice to Charon
curl -X POST http://localhost:8765/control \
  -H "Content-Type: application/json" \
  -d '{"action": "set_voice", "payload": {"event_type": "error", "voice_name": "Charon"}}'
```

```json
{"status": "ok", "action": "set_volume"}
```

---

### `GET /status` — Get Engine Status

Retrieve the current running status of the engine.

#### Response

| Field | Type | Description |
|-------|------|-------------|
| `is_running` | `boolean` | Whether the engine's playback loop is active |
| `queue_depth` | `integer` | Number of audio chunks waiting for playback |
| `tts_available` | `boolean` | Whether the TTS provider API is reachable |

#### Example

```bash
curl http://localhost:8765/status
```

```json
{
  "is_running": true,
  "queue_depth": 0,
  "tts_available": true
}
```

---

## Reference Tables

### Priority Levels

Lower number = higher priority. Higher-priority items play before lower-priority items in the queue.

| Priority | Value | Use Case |
|----------|-------|----------|
| `ERROR` | `1` | Errors, alerts — jumps the queue |
| `RESPONSE` | `2` | Normal speech, messages (default) |
| `TOOL` | `3` | Tool use/result notifications |
| `THINKING` | `4` | Thinking/reasoning (lowest priority) |

### Event Types

| Event Type | Value | Description |
|------------|-------|-------------|
| `message` | `"message"` | Normal conversational content |
| `thinking` | `"thinking"` | Internal reasoning / chain-of-thought |
| `tool_use` | `"tool_use"` | Tool invocation notification |
| `tool_result` | `"tool_result"` | Tool output (disabled by default) |
| `error` | `"error"` | Error messages |
| `skip` | `"skip"` | Internal — events that produce no audio |

### Voices

| Voice | Character | Best For |
|-------|-----------|----------|
| `Kore` | Clear, neutral | Default messages, general speech |
| `Aoede` | Warm, expressive | Narrative content, longer passages |
| `Puck` | Bright, energetic | Notifications, tool output, brief updates |
| `Zephyr` | Soft, contemplative | Thinking, inner monologue, reasoning |
| `Charon` | Deep, measured | Status reports, data readouts |
| `Fenrir` | Authoritative, alert | Errors, warnings, urgent alerts |
| `Enceladus` | Thoughtful | Alternative thinking voice |

### Default Voice Routing

These are the default voice assignments when using `POST /event`. They can be changed at runtime via `POST /control` with `set_voice`.

| Event Type | Voice | Style Prefix | Enabled | Priority |
|------------|-------|-------------|---------|----------|
| `message` | Kore | *(none)* | ✅ | RESPONSE (2) |
| `thinking` | Zephyr | `[thoughtfully, inner monologue]` | ✅ | THINKING (4) |
| `tool_use` | Puck | `[brief, matter-of-fact] Running:` | ✅ | TOOL (3) |
| `tool_result` | Charon | `[neutral, concise]` | ❌ | TOOL (3) |
| `error` | Fenrir | `[alert]` | ✅ | ERROR (1) |

> **Note:** `tool_result` is disabled by default to reduce noise. Enable it via configuration or the `set_voice` control action.

---

## Error Handling

The API is designed to **never crash** — it degrades gracefully:

| Scenario | HTTP Status | Response |
|----------|-------------|----------|
| Valid request, text queued | `200` | `{"status": "queued", "queue_depth": N}` |
| Empty text | `200` | `{"status": "skipped", "message": "Empty text."}` |
| Invalid priority value | `400` | `{"detail": "Invalid priority: 999"}` |
| Invalid event type | `400` | `{"detail": "Invalid event type: foo"}` |
| Unknown control action | `400` | `{"detail": "Unknown control action: foo"}` |
| TTS API failure | `200` | Audio queue receives a fallback noise burst |
| TTS API rate-limited (429) | `200` | Circuit breaker opens, skips silently |
| All TTS models down | `200` | Queue accepts items, plays silence |
| Missing API key | `200` | Engine runs in silent mode |

The engine never returns `5xx` errors for TTS failures. Synthesis failures are handled internally with fallback audio (short noise burst) or silent degradation.

---

## Rate Limiting & Queue Behavior

- **TTS API rate limit:** 10 requests/minute by default (configurable).
- **Max queue depth:** 5 items. When full, the oldest non-error item is evicted.
- **Stale timeout:** 10 seconds. Queued items older than this are dropped (except errors).
- **Priority ordering:** ERROR items are never evicted and always play first.
- **Sequential playback:** Items play one at a time — no clipping or overlapping.
