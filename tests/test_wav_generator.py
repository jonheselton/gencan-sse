"""Tests for gencan_sse.wav_generator module."""

import struct

from gencan_sse.wav_generator import wrap_pcm_to_wav


class TestWrapPcmToWav:
    """Tests for the wrap_pcm_to_wav() function."""

    def test_header_size(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100)
        assert len(wav) == 144  # 44 header + 100 data

    def test_riff_header(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100)
        assert wav[:4] == b"RIFF"

    def test_wave_format(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100)
        assert wav[8:12] == b"WAVE"

    def test_fmt_subchunk(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100)
        assert wav[12:16] == b"fmt "

    def test_data_subchunk(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100)
        assert wav[36:40] == b"data"

    def test_audio_format_pcm(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100)
        audio_format = struct.unpack_from("<H", wav, 20)[0]
        assert audio_format == 1  # PCM

    def test_sample_rate(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100, sample_rate=24000)
        rate = struct.unpack_from("<I", wav, 24)[0]
        assert rate == 24000

    def test_custom_sample_rate(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100, sample_rate=44100)
        rate = struct.unpack_from("<I", wav, 24)[0]
        assert rate == 44100

    def test_mono_channels(self):
        wav = wrap_pcm_to_wav(b"\x00" * 100, channels=1)
        channels = struct.unpack_from("<H", wav, 22)[0]
        assert channels == 1

    def test_data_preserved(self):
        pcm_data = bytes(range(100))
        wav = wrap_pcm_to_wav(pcm_data)
        assert wav[44:] == pcm_data

    def test_empty_pcm(self):
        wav = wrap_pcm_to_wav(b"")
        assert len(wav) == 44  # header only

    def test_chunk_size_correct(self):
        pcm_data = b"\x00" * 200
        wav = wrap_pcm_to_wav(pcm_data)
        chunk_size = struct.unpack_from("<I", wav, 4)[0]
        assert chunk_size == 36 + len(pcm_data)

    def test_data_size_correct(self):
        pcm_data = b"\x00" * 200
        wav = wrap_pcm_to_wav(pcm_data)
        data_size = struct.unpack_from("<I", wav, 40)[0]
        assert data_size == len(pcm_data)
