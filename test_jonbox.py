import asyncio
from gencan_sse.providers.jonbox import JonboxTTSProvider
import logging

logging.basicConfig(level=logging.DEBUG)

async def test():
    provider = JonboxTTSProvider(base_url="http://localhost:8080")
    pcm, meta = await provider.synthesize("Hello this is a test", "Kore")
    print("Length of PCM:", len(pcm))
    if not pcm:
        print("Failed to get PCM data from JonboxTTSProvider")

asyncio.run(test())
