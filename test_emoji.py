import asyncio
from gencan_sse.providers.jonbox import JonboxTTSProvider
import logging

logging.basicConfig(level=logging.WARNING)

async def test():
    provider = JonboxTTSProvider(base_url="http://localhost:8080")
    print("Testing emoji...")
    pcm, meta = await provider.synthesize("👍", "Kore")
    print("Length of PCM for emoji:", len(pcm))

asyncio.run(test())
