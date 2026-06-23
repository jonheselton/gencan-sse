"""macOS AVFoundation TTS provider for gencan-sse.

Uses Apple's ``AVSpeechSynthesizer`` via PyObjC to provide native, offline
text-to-speech synthesis.  Audio is captured directly into memory buffers
and resampled to the engine's expected 24 kHz 16-bit signed mono PCM format.

To avoid blocking the main application's async event loop and to properly
service the Cocoa main run loop (which AVFoundation requires for callbacks),
synthesis is delegated to a lightweight short-lived Python subprocess.

Requires macOS 10.15+ and the following packages::

    pip install pyobjc-framework-AVFoundation pyobjc-framework-Cocoa

This provider conforms to the :class:`TTSProvider` protocol and can be
passed directly to :class:`~gencan_sse.engine.SpeechEngine`.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import sys
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default voice configuration
# ---------------------------------------------------------------------------

#: Identifier for the default macOS voice (Zoe Premium, en-US).
DEFAULT_VOICE_ID: str = "com.apple.voice.premium.en-US.Zoe"
DEFAULT_VOICE_NAME: str = "Zoe (Premium)"

#: Target PCM format expected by the gencan-sse audio player.
TARGET_SAMPLE_RATE: int = 24000


def _resample_linear(
    pcm_float32: list[float],
    src_rate: int,
    dst_rate: int,
) -> list[float]:
    """Resample float32 audio samples using linear interpolation.

    Args:
        pcm_float32: Source samples as float32 values in [-1.0, 1.0].
        src_rate: Source sample rate in Hz.
        dst_rate: Destination sample rate in Hz.

    Returns:
        Resampled float32 samples at the destination rate.
    """
    if src_rate == dst_rate or not pcm_float32:
        return pcm_float32

    ratio = dst_rate / src_rate
    src_len = len(pcm_float32)
    dst_len = int(src_len * ratio)
    resampled: list[float] = []

    for i in range(dst_len):
        src_pos = i / ratio
        idx = int(src_pos)
        frac = src_pos - idx

        if idx + 1 < src_len:
            sample = pcm_float32[idx] * (1.0 - frac) + pcm_float32[idx + 1] * frac
        elif idx < src_len:
            sample = pcm_float32[idx]
        else:
            sample = 0.0

        resampled.append(sample)

    return resampled


# ---------------------------------------------------------------------------
# Subprocess synthesis script
# ---------------------------------------------------------------------------
# This script is executed in a subprocess to run the Cocoa main run loop
# and capture AVFoundation callbacks without blocking the parent asyncio loop.
_SUBPROCESS_SCRIPT = """
import sys
import struct
import threading

def synthesize_and_write(text: str, voice_id: str, speaking_rate: float):
    try:
        import AVFoundation
        import Cocoa
    except ImportError:
        sys.exit(1)

    synth = AVFoundation.AVSpeechSynthesizer.alloc().init()
    utt = AVFoundation.AVSpeechUtterance.speechUtteranceWithString_(text)
    utt.setRate_(speaking_rate)
    
    # Try exact identifier match first
    voice = AVFoundation.AVSpeechSynthesisVoice.voiceWithIdentifier_(voice_id)
    if not voice:
        # Try name match
        for v in AVFoundation.AVSpeechSynthesisVoice.speechVoices():
            if v.name() == voice_id:
                voice = v
                break
    
    if voice:
        utt.setVoice_(voice)
    
    done = threading.Event()
    source_rate = [22050]
    
    def buffer_cb(buffer):
        frames = buffer.frameLength()
        if frames == 0:
            done.set()
            return
            
        fmt = buffer.format()
        source_rate[0] = int(fmt.sampleRate())
        
        abl = buffer.audioBufferList()
        ab = abl[0]
        data = bytes(ab.mData)
        byte_size = ab.mDataByteSize
        
        bytes_per_frame = byte_size // frames if frames else 4
        
        # Write format identifier byte: 4 for float32, 2 for int16
        sys.stdout.buffer.write(struct.pack('B', bytes_per_frame))
        # Write sample rate as uint32
        sys.stdout.buffer.write(struct.pack('<I', source_rate[0]))
        # Write frames count as uint32
        sys.stdout.buffer.write(struct.pack('<I', frames))
        
        # Write the raw sample bytes
        sys.stdout.buffer.write(data[:frames * bytes_per_frame])
        sys.stdout.buffer.flush()

    synth.writeUtterance_toBufferCallback_(utt, buffer_cb)
    
    # Pump main run loop
    deadline = Cocoa.NSDate.dateWithTimeIntervalSinceNow_(30.0)
    while not done.is_set():
        Cocoa.NSRunLoop.currentRunLoop().runMode_beforeDate_(
            Cocoa.NSDefaultRunLoopMode,
            Cocoa.NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )
        if Cocoa.NSDate.date().compare_(deadline) == Cocoa.NSOrderedDescending:
            break

if __name__ == '__main__':
    text = sys.stdin.read()
    if text.strip():
        voice_id = sys.argv[1] if len(sys.argv) > 1 else "{default_voice_id}"
        rate = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
        synthesize_and_write(text, voice_id, rate)
"""


class AVFoundationTTSProvider:
    """macOS AVFoundation TTS provider implementing the TTSProvider protocol.

    Uses a lightweight subprocess to run ``AVSpeechSynthesizer`` and capture
    synthesised audio directly into memory as PCM buffers, then converts
    and resamples to 24 kHz 16-bit signed mono PCM in the parent process.

    Args:
        default_voice_id: AVSpeechSynthesisVoice identifier string.
            Defaults to Zoe (Premium) en-US.
        speaking_rate: Speech rate multiplier.  AVFoundation uses a range
            where 0.5 is normal speed, 0.0 is slowest, 1.0 is fastest.
            Defaults to 0.5 (normal).
        target_sample_rate: Output sample rate in Hz.  Defaults to 24000
            to match the gencan-sse audio player.
    """

    def __init__(
        self,
        default_voice_id: str = DEFAULT_VOICE_ID,
        speaking_rate: float = 0.5,
        target_sample_rate: int = TARGET_SAMPLE_RATE,
    ) -> None:
        self._default_voice_id = default_voice_id
        self._speaking_rate = speaking_rate
        self._target_sample_rate = target_sample_rate
        self._available = False

        try:
            import AVFoundation as _AVF  # noqa: F401
            import Cocoa as _Cocoa  # noqa: F401

            # Log available premium voices
            all_voices = _AVF.AVSpeechSynthesisVoice.speechVoices()
            premium_en = [
                v
                for v in all_voices
                if "en" in v.language() and v.quality() >= 2
            ]
            
            # Resolve default voice for logging
            resolved_name = "system default"
            av_voice = _AVF.AVSpeechSynthesisVoice.voiceWithIdentifier_(self._default_voice_id)
            if av_voice:
                resolved_name = av_voice.name()
                
            logger.info(
                "AVFoundationTTSProvider initialized — default voice: %s, "
                "premium English voices available: %s",
                resolved_name,
                [v.name() for v in premium_en],
            )
            self._available = True

        except ImportError:
            logger.warning(
                "pyobjc-framework-AVFoundation not installed. "
                "AVFoundation TTS provider disabled. Install with: "
                "pip install pyobjc-framework-AVFoundation pyobjc-framework-Cocoa"
            )

    # ------------------------------------------------------ TTSProvider API

    @property
    def name(self) -> str:
        """Human-readable name of this provider."""
        return "avfoundation"

    @property
    def is_available(self) -> bool:
        """Whether AVFoundation is importable on this system."""
        return self._available

    async def synthesize(
        self,
        text: str,
        voice: str = "Zoe (Premium)",
        style: str = "",
    ) -> tuple[bytes, dict]:
        """Synthesize *text* to raw PCM audio bytes.

        Spawns a subprocess to handle the Cocoa run loop and read callbacks,
        preventing event loop blockage in the main process.

        Args:
            text: The text to speak.
            voice: macOS voice name (e.g. ``"Zoe (Premium)"``,
                ``"Samantha"``).  Gemini-style names (e.g. ``"Kore"``) are
                not recognised and will fall back to the default voice.
            style: Style prefix — stripped before synthesis since
                AVFoundation does not support style tags.

        Returns:
            A tuple of (PCM audio bytes at 24 kHz 16-bit mono, metadata dict).
            Returns ``(b"", {})`` on failure.
        """
        if not self.is_available or not text or not text.strip():
            return b"", {}

        # Strip style prefix — AVFoundation doesn't understand style tags
        import re
        clean_text = re.sub(r"^\[[^\]]*\]\s*", "", text) if style or text.startswith("[") else text
        if not clean_text.strip():
            clean_text = text

        t0 = time.time()

        try:
            pcm_bytes = await self._synthesize_subprocess(clean_text, voice)
        except Exception as exc:
            logger.error("AVFoundation synthesis failed: %s", exc)
            return b"", {}

        elapsed = time.time() - t0

        if not pcm_bytes:
            logger.warning("AVFoundation returned empty audio for text: %r", text[:80])
            return b"", {}

        audio_bytes = len(pcm_bytes)
        duration_est = audio_bytes / (self._target_sample_rate * 2)

        logger.debug(
            "AVFoundation synthesized %d bytes (~%.1fs audio) for "
            "voice=%s, latency=%.3fs",
            audio_bytes,
            duration_est,
            voice,
            elapsed,
        )

        metadata = {
            "model": "avfoundation",
            "provider": self.name,
            "latency_ms": elapsed * 1000,
            "audio_bytes": audio_bytes,
        }

        return pcm_bytes, metadata

    # ------------------------------------------------- internal synthesis

    async def _synthesize_subprocess(self, text: str, voice_name: str) -> bytes:
        """Run AVFoundation synthesis in a subprocess and parse the output."""
        script = _SUBPROCESS_SCRIPT.replace("{default_voice_id}", self._default_voice_id)
        
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script, voice_name, str(self._speaking_rate),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout_data, stderr_data = await proc.communicate(input=text.encode("utf-8"))
        
        if proc.returncode != 0:
            logger.error("AVFoundation subprocess failed with code %s: %s", 
                         proc.returncode, stderr_data.decode("utf-8", errors="ignore"))
            return b""
            
        if not stdout_data:
            return b""
            
        # Parse the custom binary protocol written by the subprocess
        # Format: [byte(format_id), uint32(sample_rate), uint32(frames), bytes(data)] * chunks
        offset = 0
        float_samples: list[float] = []
        source_rate = 22050
        
        while offset < len(stdout_data):
            if offset + 9 > len(stdout_data):
                break
                
            fmt_id = stdout_data[offset]
            offset += 1
            source_rate = struct.unpack_from("<I", stdout_data, offset)[0]
            offset += 4
            frames = struct.unpack_from("<I", stdout_data, offset)[0]
            offset += 4
            
            chunk_bytes = frames * fmt_id
            if offset + chunk_bytes > len(stdout_data):
                break
                
            chunk_data = stdout_data[offset:offset+chunk_bytes]
            offset += chunk_bytes
            
            if fmt_id == 4:
                # float32
                samples = struct.unpack(f"<{frames}f", chunk_data)
                float_samples.extend(samples)
            elif fmt_id == 2:
                # int16
                samples = struct.unpack(f"<{frames}h", chunk_data)
                float_samples.extend(s / 32768.0 for s in samples)
                
        if not float_samples:
            return b""

        # Resample from source rate to target rate
        resampled = _resample_linear(float_samples, source_rate, self._target_sample_rate)

        # Convert float32 → 16-bit signed PCM
        pcm_data = bytearray()
        for sample in resampled:
            clamped = max(-1.0, min(1.0, sample))
            i16 = int(clamped * 32767)
            pcm_data.extend(struct.pack("<h", i16))

        return bytes(pcm_data)
