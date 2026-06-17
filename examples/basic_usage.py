#!/usr/bin/env python3
"""Basic usage example for gencan-sse.

Demonstrates the simplest possible usage of the SpeechEngine.

Usage:
    python examples/basic_usage.py "Your text here"
    python examples/basic_usage.py  # uses default text
"""

import sys
import time

from gencan_sse import SpeechEngine


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello from GenCan Speech Synthesis Engine!"

    # Create and start the engine with defaults
    engine = SpeechEngine()
    engine.start()

    print(f"Speaking: {text!r}")
    result = engine.speak(text)
    print(f"Result: {result}")

    # Wait for audio to finish playing
    # (The engine is async internally, so we give it time to synthesize and play)
    time.sleep(5.0)

    engine.stop()
    print("Done!")


if __name__ == "__main__":
    main()
