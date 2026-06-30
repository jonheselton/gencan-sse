import asyncio
from gencan_sse.providers.jonbox import JonboxTTSProvider

async def test():
    provider = JonboxTTSProvider(base_url="http://localhost:8080")
    for txt in ["...", "!", "   ", "\n", "Hmmm"]:
        print(f"Testing '{txt}'...")
        pcm, meta = await provider.synthesize(txt, "Kore")
        print(f"Length of PCM for '{txt}':", len(pcm))

asyncio.run(test())
