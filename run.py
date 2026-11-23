"""Agent-OS Entry Point

Runs the Agent-OS demo or starts the FastAPI server.
Usage:
    python run.py demo    - Run the generic demonstration
    python run.py server  - Start the FastAPI API server
    python run.py         - Default: run demo
"""
import sys
import asyncio
from pathlib import Path

# Add src/ to path for `agent_os`, and project root for `sdk` package
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if mode == "demo":
        from examples.generic.demo import main as demo_main
        asyncio.run(demo_main())
    elif mode == "server":
        import uvicorn
        from agent_os.api.app import app
        print("Starting Agent-OS API server...")
        print("Open in browser: http://127.0.0.1:8000")
        print("Swagger UI docs: http://127.0.0.1:8000/docs")
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python run.py [demo|server]")
        sys.exit(1)

if __name__ == "__main__":
    main()
