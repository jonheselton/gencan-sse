import asyncio
from mlx_audio.tts.generate import generate_audio
import wave

async def test():
    generate_audio(
        text="Testing",
        model="prince-canuma/Kokoro-82M",
        voice="af_heart",
        speed=1.0,
        audio_format="wav",
        file_prefix="test_kokoro",
        save=True
    )
    import os
    path = "test_kokoro.wav"
    if os.path.exists(path):
        with wave.open(path, "rb") as wf:
            print("Channels:", wf.getnchannels())
            print("Sample Width:", wf.getsampwidth())
            print("Framerate:", wf.getframerate())
            print("nframes:", wf.getnframes())

asyncio.run(test())
