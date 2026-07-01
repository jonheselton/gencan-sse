"""
WAV generator utility for gencan-sse.
Provides functions to wrap raw PCM audio data into a standard WAV container.
"""

import struct


def wrap_pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 24000,
    sample_width: int = 2,
    channels: int = 1,
) -> bytes:
    """
    Wraps raw PCM audio bytes into a standard 44-byte WAV (RIFF/WAVE) file format.

    Args:
        pcm_data: The raw PCM audio bytes to wrap.
        sample_rate: Sampling rate of the audio (e.g., 24000, 16000, 44100).
        sample_width: Sample size in bytes (e.g., 2 for 16-bit audio).
        channels: Number of audio channels (e.g., 1 for mono, 2 for stereo).

    Returns:
        The complete WAV file content as bytes, consisting of a 44-byte header
        followed by the original PCM data.
    """
    if sample_rate <= 0 or sample_width <= 0 or channels <= 0:
        raise ValueError("sample_rate, sample_width, and channels must be greater than zero")

    bits_per_sample = sample_width * 8
    block_align = channels * sample_width
    byte_rate = sample_rate * block_align

    # Subchunk2Size is the length of the actual data
    data_size = len(pcm_data)
    
    # ChunkSize is the total size of the file minus 8 bytes (RIFF and ChunkSize fields)
    # Header is 44 bytes, so chunk_size = 44 + data_size - 8 = 36 + data_size
    chunk_size = 36 + data_size

    # Pack the 44-byte header using little-endian formats:
    # 4s -> ChunkID (b"RIFF")
    # I  -> ChunkSize (chunk_size)
    # 4s -> Format (b"WAVE")
    # 4s -> Subchunk1ID (b"fmt ")
    # I  -> Subchunk1Size (16 for PCM)
    # H  -> AudioFormat (1 for uncompressed PCM)
    # H  -> NumChannels (channels)
    # I  -> SampleRate (sample_rate)
    # I  -> ByteRate (byte_rate)
    # H  -> BlockAlign (block_align)
    # H  -> BitsPerSample (bits_per_sample)
    # 4s -> Subchunk2ID (b"data")
    # I  -> Subchunk2Size (data_size)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )

    return header + pcm_data
