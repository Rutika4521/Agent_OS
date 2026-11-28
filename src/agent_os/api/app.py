"""
Agent-OS API Application (FastAPI)

Provides the REST API server for Agent-OS.
Initializes the kernel AND persistence layer on startup.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from agent_os.config.settings import Settings
from agent_os.api.routes import router, set_demo_components, use_kernel

# Persistence (optional — gracefully disabled if sqlalchemy not installed)
_db_manager = None
try:
    from agent_os.persistence.database import DatabaseManager
    _HAS_PERSISTENCE = True
except ImportError:
    _HAS_PERSISTENCE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot the Agent-OS kernel + persistence layer when the server starts."""
    from agent_os.sdk.kernel import Kernel

    settings = Settings()
    kernel = Kernel(settings)          # the real Agent-OS kernel: scheduler, supervisor, sync, ...
    await kernel.boot()

    # ── Phase 7: Boot persistence layer ───────────────────────────────────
    global _db_manager
    if _HAS_PERSISTENCE:
        try:
            _db_manager = DatabaseManager(settings.persistence.database_url)
            await _db_manager.initialize()
            print(f"[Agent-OS] Persistence layer online: {settings.persistence.database_url}")
        except Exception as e:
            print(f"[Agent-OS] Persistence unavailable (continuing without it): {e}")
            _db_manager = None
    else:
        print("[Agent-OS] Persistence disabled (sqlalchemy/aiosqlite not installed)")

    use_kernel(kernel)                 # REST cancel/pause/resume go through the kernel
    set_demo_components(
        supervisor=kernel.supervisor,
        ipc_manager=kernel.ipc,
        event_manager=kernel.events,
        process_manager=kernel.pm,
    )
    print("[Agent-OS] Kernel booted successfully.")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    if _db_manager:
        await _db_manager.close()
    await kernel.shutdown()
    print("[Agent-OS] Kernel shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent-OS API",
        description=(
            "REST API for Agent-OS: treating LLM agents as first-class OS processes. "
            "Provides scheduling, IPC, memory, supervisor, and deadlock detection."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/docs")

    return app


app = create_app()
