import os
import asyncio
from gencan_sse.providers.gemini import GeminiTTSProvider

async def test():
    # Force debug logging
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    provider = GeminiTTSProvider(
        max_concurrent=1,
        max_retries=1,
    )
    
    # Try synthesis
    print("Models configured:", provider._models)
    print("Local client configured:", provider._local_client is not None)
    
    audio, metadata = await provider.synthesize("Hello world", "Kore")
    if audio:
        print("Success! Audio length:", len(audio))
    else:
        print("Failed to synthesize audio.")

if __name__ == "__main__":
    asyncio.run(test())
