"""Agent-OS Entry Point

Runs the Agent-OS demo or starts the FastAPI server.
Usage:
    python run.py demo    - Run the generic demonstration
    python run.py server  - Start the FastAPI API server
    python run.py         - Default: run demo
"""
import sys
import asyncio

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if mode == "demo":
        from examples.generic.demo import main as demo_main
        asyncio.run(demo_main())
    elif mode == "server":
        import uvicorn
        from agent_os.api.app import app
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python run.py [demo|server]")
        sys.exit(1)

if __name__ == "__main__":
    main()
