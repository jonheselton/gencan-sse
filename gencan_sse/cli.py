"""Command-line interface for the GenCan SSE daemon."""

import argparse
import logging
import sys

def main():
    """Entry point for the gencan-server executable."""
    parser = argparse.ArgumentParser(
        description="Run the GenCan Speech Synthesis Engine as a local daemon service."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="The interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="The port to bind to (default: 8765)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging level",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode (defaults port to 8766, log-level to debug)",
    )

    args = parser.parse_args()

    if args.dev:
        import os
        os.environ["GENCAN_DEV"] = "true"
        # Only override port and log level if they weren't explicitly passed in command-line arguments
        if not any(arg.startswith("--port") for arg in sys.argv):
            args.port = 8766
        if not any(arg.startswith("--log-level") for arg in sys.argv):
            args.log_level = "debug"

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is not installed. Please install with the server extras:\n"
            "  pip install -e '.[server]'",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Starting GenCan SSE daemon on http://{args.host}:{args.port}")
    uvicorn.run(
        "gencan_sse.server.app:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )

if __name__ == "__main__":
    main()
