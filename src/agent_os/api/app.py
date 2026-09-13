from fastapi import FastAPI
from agent_os.api.routes import router

def create_app() -> FastAPI:
    app = FastAPI(title="Agent-OS API")
    app.include_router(router)
    return app

app = create_app()
