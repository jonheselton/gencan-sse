import asyncio
from gencan_sse.providers.jonbox import JonboxTTSProvider
import logging

logging.basicConfig(level=logging.WARNING)

async def test():
    provider = JonboxTTSProvider(base_url="http://localhost:8080")
    
    voices = ["Kore", "Zephyr", "Puck", "Charon", "Fenrir"]
    for voice in voices:
        print(f"Testing {voice}...")
        pcm, meta = await provider.synthesize("Hello", voice)
        print(f"Length of PCM for {voice}:", len(pcm))

asyncio.run(test())
