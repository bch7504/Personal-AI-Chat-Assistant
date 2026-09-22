import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import src.db.session as db_session
from src.agents import graph as agent_graph
from src.agents.runtime.adapters import (
    product_delivery_runtime_ready,
    quality_assurance_runtime_ready,
)
from src.api.admin_routes import router as admin_router
from src.api.agent_workspace_routes import router as agent_workspace_router
from src.api.assistant_routes import router as assistant_router
from src.api.auth_routes import router as auth_router
from src.api.calendar_routes import public_router as calendar_public_router
from src.api.calendar_routes import router as calendar_router
from src.api.chat_routes import router as chat_router
from src.api.delivery_routes import router as delivery_router
from src.api.memory_routes import router as memory_router
from src.api.platform_routes import router as platform_router
from src.api.quality_control_routes import router as quality_control_router
from src.api.quality_routes import router as quality_router
from src.api.rate_limit import RateLimitMiddleware
from src.api.relationship_routes import router as relationship_router
from src.api.release_candidate_routes import router as release_candidate_router
from src.api.reminder_routes import router as reminder_router
from src.api.routes import router
from src.api.runtime_progress_routes import router as runtime_progress_router
from src.api.task_routes import router as task_router
from src.api.timeline_routes import router as timeline_router
from src.api.workspace_action_routes import router as workspace_action_router
from src.api.workspace_agent_metrics_routes import router as workspace_agent_metrics_router
from src.api.workspace_agent_router_routes import router as workspace_agent_gateway_router
from src.api.workspace_routes import router as workspace_router
from src.config import get_settings
from src.db.session import init_db
from src.services import calendar_service, thread_memory_service, workspace_agent_memory_service
from src.services.ai_config_service import load_saved_ai_configuration
from src.services.company_service import get_or_create_company_workspace
from src.services.component_health_service import component_health
from src.services.delivery_group_schedule_service import process_due_delivery_group_schedules
from src.services.reminder_service import reconcile_active_task_reminders
from src.services.scheduler import scheduler
from src.services.workspace_outbox_service import process_workspace_outbox_events
from src.websocket.routes import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Backward-compatible lifecycle hooks. Tests and deployment wrappers may patch
# these names without reaching into the Personal Agent implementation module.
init_checkpointer = agent_graph.init_checkpointer
close_checkpointer = agent_graph.close_checkpointer


async def initialize_personal_agent_component() -> bool:
    """Initialize Personal independently so its failure cannot take Core/Delivery down."""

    try:
        await init_checkpointer()
    except Exception:  # noqa: BLE001 - this is the intended fault boundary.
        logger.exception("Personal Agent checkpointer failed; Core will continue in degraded mode")
        component_health.set("personal_agent", ready=False, detail="checkpointer initialization failed")
        return False
    component_health.set("personal_agent", ready=True, detail="ready")
    return True


async def cleanup_workspace_agent_memory() -> None:
    """Run retention cleanup without making it a Core startup dependency."""

    try:
        await workspace_agent_memory_service.cleanup_expired_threads()
    except Exception:  # noqa: BLE001 - cleanup failure must not take Core down.
        logger.exception("Workspace Agent memory cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    if settings.app_env != "production":
        await init_db()
    component_health.set("core_database", ready=True, detail="database initialized")
    async with db_session.async_session_maker() as db:
        await get_or_create_company_workspace(db)
        await db.commit()
    await load_saved_ai_configuration()
    personal_ready = await initialize_personal_agent_component()
    if personal_ready:
        await thread_memory_service.cleanup_expired_threads()
    await cleanup_workspace_agent_memory()
    scheduler.start()
    if personal_ready:
        scheduler.add_job(
            thread_memory_service.cleanup_expired_threads,
            "interval",
            hours=1,
            id="agent_thread_cleanup",
            replace_existing=True,
        )
    scheduler.add_job(
        cleanup_workspace_agent_memory,
        "interval",
        minutes=settings.workspace_agent_memory_cleanup_interval_minutes,
        id="workspace_agent_memory_cleanup",
        replace_existing=True,
    )
    scheduler.add_job(
        calendar_service.poll_calendar_changes,
        "interval",
        seconds=settings.calendar_poll_interval_seconds,
        id="calendar_poll",
        replace_existing=True,
    )
    scheduler.add_job(
        reconcile_active_task_reminders,
        "interval",
        minutes=15,
        id="task_reminder_reconcile",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_workspace_outbox_events,
        "interval",
        seconds=10,
        id="workspace_agent_outbox",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_due_delivery_group_schedules,
        "interval",
        seconds=10,
        id="delivery_group_schedules",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    yield
    scheduler.shutdown(wait=False)
    await close_checkpointer()
    print("Shutting down...")


app = FastAPI(
    title="Orbit",
    description="Local personal AI assistant built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
component_health.set("core_api", ready=True, detail="process is live")
component_health.set(
    "product_delivery_runtime",
    ready=(
        settings.workspace_agent_runtime_mode == "embedded"
        or bool(settings.workspace_agent_runtime_url and settings.workspace_agent_runtime_secret)
    ),
    detail=f"{settings.workspace_agent_runtime_mode} adapter configured",
)
component_health.set(
    "quality_assurance_runtime",
    ready=(
        settings.workspace_agent_runtime_mode == "embedded"
        or bool(settings.quality_assurance_runtime_url and settings.quality_assurance_runtime_secret)
    ),
    detail=f"{settings.workspace_agent_runtime_mode} adapter configured",
)
if agent_graph.agent is not None:
    component_health.set("personal_agent", ready=True, detail="in-memory checkpointer ready")
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])
app.include_router(ws_router, prefix="/api/v1", tags=["ws"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(platform_router, prefix="/api/v1/platform", tags=["platform"])
app.include_router(workspace_router, prefix="/api/v1/workspaces", tags=["workspaces"])
app.include_router(agent_workspace_router, prefix="/api/v1/workspaces", tags=["agent-workspaces"])
app.include_router(delivery_router, prefix="/api/v1", tags=["delivery-agent"])
app.include_router(quality_router, prefix="/api/v1", tags=["quality-agent"])
app.include_router(quality_control_router, prefix="/api/v1", tags=["quality-control-plane"])
app.include_router(release_candidate_router, prefix="/api/v1", tags=["release-handoff"])
app.include_router(workspace_agent_gateway_router, prefix="/api/v1", tags=["workspace-agent-router"])
app.include_router(workspace_agent_metrics_router, prefix="/api/v1", tags=["workspace-agent-metrics"])
app.include_router(workspace_action_router, prefix="/api/v1", tags=["workspace-agent-actions"])
app.include_router(relationship_router, prefix="/api/v1/workspaces", tags=["relationships"])
app.include_router(task_router, prefix="/api/v1", tags=["tasks"])
app.include_router(timeline_router, prefix="/api/v1", tags=["timeline"])
app.include_router(calendar_router, prefix="/api/v1", tags=["calendar"])
app.include_router(calendar_public_router, prefix="/api/v1", tags=["calendar"])
app.include_router(reminder_router, prefix="/api/v1", tags=["reminders"])
app.include_router(memory_router, prefix="/api/v1", tags=["memory"])
app.include_router(assistant_router, prefix="/api/v1", tags=["assistant"])
app.include_router(runtime_progress_router, tags=["internal-runtime"])


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/components")
async def component_health_report():
    return {"status": "ok", "components": component_health.snapshot()}


@app.get("/health/ready")
async def readiness():
    (delivery_ready, delivery_detail), (quality_ready, quality_detail) = await asyncio.gather(
        product_delivery_runtime_ready(),
        quality_assurance_runtime_ready(),
    )
    component_health.set(
        "product_delivery_runtime",
        ready=delivery_ready,
        detail=delivery_detail,
    )
    component_health.set(
        "quality_assurance_runtime",
        ready=quality_ready,
        detail=quality_detail,
    )
    components = component_health.snapshot()
    core_ready = all(components.get(name, {}).get("ready", False) for name in ("core_api", "core_database"))
    degraded = any(not item["ready"] for item in components.values())
    return {
        "status": "degraded" if degraded else "ready",
        "ready": core_ready,
        "components": components,
    }
