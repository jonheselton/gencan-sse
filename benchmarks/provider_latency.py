"""Measure TTS provider latency and save a demo clip from each.

Usage::

    source ~/.zshrc  # for GEMINI_API_KEY
    .venv/bin/python benchmarks/provider_latency.py --runs 3 --out /tmp/tts-demo

For every provider this records wall-clock time per call (none of the current
providers stream, so this is also time-to-first-audio), the length of audio
produced, and the real-time factor (synthesis time / audio length; lower is
better).  It also tests "Kokoro (model kept loaded)", which keeps the model in
memory between calls and yields audio sentence by sentence, to show how much
faster Kokoro could be than the current provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
import wave
from pathlib import Path

SAMPLE_RATE = 24_000
TEXT = (
    "Hello, this is {name}. The build finished and all forty two tests passed. "
    "Would you like me to open a pull request for review?"
)


def write_wav(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)


async def time_provider(label, spoken, synth, runs, out_dir):
    rows, clip = [], b""
    for i in range(runs):
        t0 = time.perf_counter()
        try:
            pcm, meta = await synth(TEXT.format(name=spoken))
            first = meta.get("first_audio_s")
        except Exception as exc:  # keep going; report the failure
            pcm, first, meta = b"", None, {"error": str(exc)}
        elapsed = time.perf_counter() - t0
        audio_s = len(pcm) / (SAMPLE_RATE * 2)
        rows.append({
            "run": i + 1,
            "ok": bool(pcm),
            "total_s": round(elapsed, 3),
            "first_audio_s": round(first if first is not None else elapsed, 3),
            "audio_s": round(audio_s, 2),
            "rtf": round(elapsed / audio_s, 3) if audio_s else None,
            "model": meta.get("model"),
            "error": meta.get("error"),
        })
        print(f"  {label} run {i + 1}: {rows[-1]}", flush=True)
        if pcm:
            clip = pcm
    if clip:
        write_wav(out_dir / f"{label.lower().replace(' ', '_').replace('(', '').replace(')', '')}.wav", clip)
    ok = [r for r in rows if r["ok"]]
    warm = ok[1:] or ok
    return {
        "provider": label,
        "success": f"{len(ok)}/{runs}",
        "cold_s": ok[0]["total_s"] if ok else None,
        "warm_median_s": round(statistics.median(r["total_s"] for r in warm), 3) if warm else None,
        "warm_first_audio_s": round(statistics.median(r["first_audio_s"] for r in warm), 3) if warm else None,
        "audio_s": ok[-1]["audio_s"] if ok else None,
        "warm_rtf": round(statistics.median(r["rtf"] for r in warm), 3) if warm else None,
        "runs": rows,
    }


def gemini_synth(model):
    from gencan_sse.providers.gemini import GeminiTTSProvider

    p = GeminiTTSProvider(model=model, fallback_models=[model], requests_per_minute=0, max_retries=1)
    if not p.is_available:
        return None

    async def synth(text):
        return await p.synthesize(text, voice="Kore")
    return synth


def avf_synth(voice):
    from gencan_sse.providers.avfoundation import AVFoundationTTSProvider

    p = AVFoundationTTSProvider()
    if not p.is_available:
        return None

    async def synth(text):
        return await p.synthesize(text, voice=voice)
    return synth


def kokoro_provider_synth():
    from gencan_sse.providers.kokoro import KokoroTTSProvider

    p = KokoroTTSProvider(model_path=KOKORO_MODEL)
    if not p.is_available:
        return None

    async def synth(text):
        return await p.synthesize(text, voice="af_heart")
    return synth


def kokoro_persistent_synth():
    import numpy as np
    from gencan_sse.providers.kokoro import _use_bundled_espeak

    _use_bundled_espeak()
    from mlx_audio.tts.utils import load_model

    model = load_model(model_path=KOKORO_MODEL)

    def run(text):
        t0 = time.perf_counter()
        first, parts = None, []
        for r in model.generate(text, voice="af_heart", lang_code="a", split_pattern=r"(?<=[.!?])\s+"):
            if first is None:
                first = time.perf_counter() - t0
            parts.append(np.asarray(r.audio))
        audio = np.concatenate(parts)
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        return pcm, {"model": "Kokoro-82M (MLX, persistent)", "first_audio_s": first}

    async def synth(text):
        return await asyncio.to_thread(run, text)
    return synth


KOKORO_MODEL = "mlx-community/Kokoro-82M-bf16"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("tts-demo"))
    ap.add_argument("--only", nargs="*", help="labels to run (substring match)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.ERROR)

    candidates = [
        ("Gemini Flash", "Gemini Flash", lambda: gemini_synth("gemini-2.5-flash-preview-tts")),
        ("Gemini Pro", "Gemini Pro", lambda: gemini_synth("gemini-2.5-pro-preview-tts")),
        ("Apple Ava Premium", "Apple Ava", lambda: avf_synth("Ava (Premium)")),
        ("Kokoro provider", "Kokoro", kokoro_provider_synth),
        ("Kokoro persistent", "Kokoro", kokoro_persistent_synth),
    ]
    results = []
    for label, spoken, factory in candidates:
        if args.only and not any(o.lower() in label.lower() for o in args.only):
            continue
        print(f"== {label}", flush=True)
        synth = factory()
        if synth is None:
            print("  unavailable", flush=True)
            results.append({"provider": label, "success": "unavailable"})
            continue
        results.append(await time_provider(label, spoken, synth, args.runs, args.out))

    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    print("\nprovider                 ok    cold_s  warm_s  first_audio_s  audio_s  rtf")
    for r in results:
        print(f"{r['provider']:<24} {r['success']:<5} {r.get('cold_s')!s:<7} {r.get('warm_median_s')!s:<7} "
              f"{r.get('warm_first_audio_s')!s:<14} {r.get('audio_s')!s:<8} {r.get('warm_rtf')}")


if __name__ == "__main__":
    asyncio.run(main())
