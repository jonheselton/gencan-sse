# TTS Provider Comparison — Goals

> **Branch:** `research/tts-provider-comparison`
> **Started:** 2026-09-16
> **Status:** Goals defined — evaluation not yet started

## Purpose

Compare the speech providers already in `gencan_sse/providers/` against
candidate new providers, to decide which to add, improve, or retire.

## Goals

1. **Inventory existing providers** — document how each works, its
   dependencies, and how it plugs into the engine and cross-provider fallback.
2. **Identify candidates** — Piper and other options not yet considered
   (local and cloud).
3. **Evaluate on shared criteria** (below) with reproducible measurements
   where possible.
4. **Recommend** — which providers to add, which to keep as fallbacks, and
   the integration work each would need.

## Existing providers

| Provider | Module | Type |
|---|---|---|
| Gemini | `providers/gemini.py` | Cloud API (rate limits, model fallback, circuit breaker) |
| AVFoundation | `providers/avfoundation.py` | macOS native, offline |
| Kokoro (MLX) | `providers/kokoro.py` | Local model, Apple Silicon |
| Jonbox | `providers/jonbox.py` | Self-hosted HTTP endpoint |

## Candidates

- Piper
- Others to be identified

## Evaluation criteria

- **Latency** — time to first audio; streaming support
- **Cost** — API pricing vs. local compute
- **Voice quality & range** — naturalness, voice count, style/prosody control
- **Platform** — macOS / Apple Silicon support, CPU vs. GPU, model size
- **Reliability** — rate limits, offline capability, failure modes
- **Integration fit** — conformance to `TTSProvider` (`providers/base.py`),
  24 kHz 16-bit mono PCM output, role in fallback chain
- **Accessibility** — suitability for continuous spoken output for
  low-vision users (clarity, pacing control, low latency)

## Out of scope (for now)

- Changing engine/queue architecture beyond what a new provider requires
