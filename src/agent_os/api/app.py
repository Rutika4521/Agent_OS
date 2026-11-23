"""
Agent-OS API Application (FastAPI)

Provides the REST API server for Agent-OS.
Initializes the kernel AND persistence layer on startup.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys

# Ensure sdk/ is importable (needed for routes.py which imports sdk.agent)
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from agent_os.config.settings import Settings
from agent_os.metrics.events import EventManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.process_manager import ProcessManager
from agent_os.resources.manager import ResourceManager
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.restart import RestartManager
from agent_os.metrics.collector import MetricsCollector
from agent_os.api.routes import router, set_kernel_state, set_demo_components

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
    settings           = Settings()
    event_manager      = EventManager()
    process_table      = ProcessTable()
    process_manager    = ProcessManager(process_table, event_manager, settings)
    resource_manager   = ResourceManager(settings)
    ipc_manager        = IPCManager(settings, event_manager)
    context_manager    = ContextManager(settings, event_manager)
    checkpoint_manager = CheckpointManager(event_manager)
    restart_manager    = RestartManager(settings.supervisor)
    supervisor         = Supervisor(
        process_manager, restart_manager, event_manager, checkpoint_manager
    )
    metrics_collector  = MetricsCollector()

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

    set_kernel_state(
        process_manager=process_manager,
        event_manager=event_manager,
        metrics_collector=metrics_collector,
        ipc_manager=ipc_manager,
    )
    set_demo_components(
        supervisor=supervisor,
        ipc_manager=ipc_manager,
        event_manager=event_manager,
        process_manager=process_manager,
    )
    print("[Agent-OS] Kernel booted successfully.")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    if _db_manager:
        await _db_manager.close()
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
