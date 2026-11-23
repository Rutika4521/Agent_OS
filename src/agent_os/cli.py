"""Agent-OS CLI Entry Point."""
from __future__ import annotations
import sys
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description="Agent-OS — Operating System for LLM Agents",
    )
    sub = parser.add_subparsers(dest="command")

    # server
    srv = sub.add_parser("server", help="Start the Agent-OS REST API server")
    srv.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    srv.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    srv.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    # version
    sub.add_parser("version", help="Print Agent-OS version")

    args = parser.parse_args()

    if args.command == "server":
        try:
            import uvicorn
            from agent_os.api.app import app
            uvicorn.run(
                "agent_os.api.app:app",
                host=args.host,
                port=args.port,
                reload=args.reload,
            )
        except ImportError:
            print("uvicorn not found. Install with: pip install uvicorn[standard]")
            sys.exit(1)

    elif args.command == "version":
        print("agent-os 0.1.0")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
