import argparse
import json
import logging
import sys
import urllib.request
import urllib.error

def send_control_request(host: str, port: int, action: str, payload: dict | None = None) -> None:
    """Send a control request to the running gencan daemon."""
    url = f"http://{host}:{port}/control"
    req_data = json.dumps({"action": action, "payload": payload or {}}).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"Success: {data.get('message', data.get('status', 'ok'))}")
    except urllib.error.URLError as e:
        print(f"Error contacting daemon at {url}: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_history(host: str, port: int, limit: int = 20) -> None:
    """Fetch spoken history from the daemon."""
    url = f"http://{host}:{port}/history?limit={limit}"
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"Spoken History (Total: {data.get('total_count', 0)}, Unread: {data.get('unread_count', 0)}):")
            for item in data.get("history", []):
                away_tag = " [AWAY]" if item.get("was_away") else ""
                print(f"  • [{item.get('event_type')}] ({item.get('voice')}){away_tag}: {item.get('text')}")
    except urllib.error.URLError as e:
        print(f"Error contacting daemon at {url}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Entry point for the gencan-server executable."""
    parser = argparse.ArgumentParser(
        description="Run or control the GenCan Speech Synthesis Engine daemon."
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # Serve command (default if no subcommand given)
    serve_parser = subparsers.add_parser("serve", help="Start the daemon server")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--log-level", type=str, default="info", choices=["debug", "info", "warning", "error", "critical"])
    serve_parser.add_argument("--dev", action="store_true")

    # Control subcommands
    subparsers.add_parser("pause", help="Pause speech playback")
    subparsers.add_parser("resume", help="Resume speech playback")

    away_parser = subparsers.add_parser("away", help="Toggle or set Away Mode")
    away_parser.add_argument("--off", action="store_true", help="Disable Away Mode")

    replay_parser = subparsers.add_parser("replay", help="Replay recent history items")
    replay_parser.add_argument("--count", type=int, default=1, help="Number of items to replay")
    replay_parser.add_argument("--unread", action="store_true", help="Replay unread items only")

    subparsers.add_parser("catchup", help="Speak catch-up summary of missed updates")

    history_parser = subparsers.add_parser("history", help="Show spoken history")
    history_parser.add_argument("--limit", type=int, default=20, help="Number of items to view")

    # Root args for fallback / legacy invocation `gencan-server --host ...`
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", type=str, default="info", choices=["debug", "info", "warning", "error", "critical"])
    parser.add_argument("--dev", action="store_true")

    args = parser.parse_args()

    # Route subcommands
    if args.command == "pause":
        send_control_request(args.host, args.port, "pause")
        return
    elif args.command == "resume":
        send_control_request(args.host, args.port, "resume")
        return
    elif args.command == "away":
        enabled = not args.off
        send_control_request(args.host, args.port, "set_away_mode", {"enabled": enabled})
        return
    elif args.command == "replay":
        send_control_request(args.host, args.port, "replay", {"count": args.count, "unread_only": args.unread})
        return
    elif args.command == "catchup":
        send_control_request(args.host, args.port, "catchup_summary")
        return
    elif args.command == "history":
        fetch_history(args.host, args.port, limit=args.limit)
        return

    if args.dev:
        import os
        os.environ["GENCAN_DEV"] = "true"
        if not any(arg == "--port" or arg.startswith("--port=") for arg in sys.argv):
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
