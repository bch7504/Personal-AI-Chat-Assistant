from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.dependencies import require_admin
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    AIPermission,
    AuditLog,
    Conversation,
    GoogleCalendarCredential,
    Memory,
    Message,
    Reminder,
    SystemConfig,
    Task,
    User,
)
from src.db.session import get_db
from src.models.admin_schemas import (
    AdminAIManagement,
    AdminAIUsageReport,
    AdminAuditLogOut,
    AdminAuditLogPage,
    AdminMemoryOut,
    AdminReminderOut,
    AdminStats,
    AdminSystemHealth,
    AdminTaskOut,
    AdminUserOut,
    UpdateAIConfigurationRequest,
    UpdateBudgetRequest,
    UpdateRoleRequest,
    UpdateStatusRequest,
)
from src.models.agent_workspace_schemas import AdminWorkspaceSummaryOut
from src.models.workspace_schemas import AdminOrganizationWorkspaceCreate, WorkspaceOut
from src.services import ai_config_service, reminder_service, usage_service
from src.services.audit_service import record_audit_event
from src.services.authorization_service import require_support_scope
from src.services.company_service import get_or_create_company_workspace
from src.services.scheduler import scheduler
from src.websocket.manager import manager

router = APIRouter(dependencies=[Depends(require_admin)])


async def _get_user_or_404(user_id: str, db: AsyncSession) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _conversation_label(conversation: Conversation | None) -> str | None:
    if conversation is None:
        return None
    return conversation.name or ("Direct message" if conversation.type == "direct" else "Group chat")


@router.get("/stats", response_model=AdminStats)
async def get_stats(db: AsyncSession = Depends(get_db)) -> AdminStats:
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    total_conversations = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()
    total_messages = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
    since = datetime.now(UTC) - timedelta(days=7)
    new_users = (await db.execute(select(func.count()).select_from(User).where(User.created_at >= since))).scalar_one()

    budget = await usage_service.get_daily_token_budget()
    usage = await usage_service.get_usage_today()
    peak_account_usage = await usage_service.get_peak_account_usage_today()
    budget_used_pct = round(peak_account_usage / budget * 100, 1) if budget else 0.0
    return AdminStats(
        total_users=total_users,
        total_conversations=total_conversations,
        total_messages=total_messages,
        new_users_last_7_days=new_users,
        tokens_used_today=usage["total_tokens"],
        prompt_tokens_today=usage["prompt_tokens"],
        completion_tokens_today=usage["completion_tokens"],
        requests_today=usage["request_count"],
        estimated_cost_usd_today=usage["estimated_cost_usd"],
        unpriced_tokens_today=usage["unpriced_tokens"],
        daily_token_budget=budget,
        budget_used_pct=budget_used_pct,
    )


@router.get("/system-health", response_model=AdminSystemHealth)
async def get_system_health(db: AsyncSession = Depends(get_db)) -> AdminSystemHealth:
    settings = get_settings()
    components: list[dict[str, str]] = []
    try:
        await db.execute(select(1))
        dialect = db.get_bind().dialect.name
        components.append(
            {"key": "database", "label": "Database", "status": "operational", "detail": f"{dialect} connected"}
        )
    except Exception:  # noqa: BLE001 - health response reports dependency failure
        components.append({"key": "database", "label": "Database", "status": "down", "detail": "Connection failed"})

    scheduler_running = scheduler.running
    jobs = len(scheduler.get_jobs()) if scheduler_running else 0
    components.append(
        {
            "key": "scheduler",
            "label": "Scheduler",
            "status": "operational" if scheduler_running else "degraded",
            "detail": f"Running with {jobs} jobs" if scheduler_running else "Not running",
        }
    )
    connections = sum(len(items) for items in manager.active.values())
    components.append(
        {
            "key": "websocket",
            "label": "WebSocket",
            "status": "operational",
            "detail": f"{connections} active connections across {len(manager.active)} users",
        }
    )
    provider_keys = {
        "google": settings.google_api_key,
        "groq": settings.groq_api_key,
        "openai": settings.openai_api_key,
        "openrouter": settings.openrouter_api_key,
    }
    llm_configured = bool(provider_keys[settings.llm_provider])
    components.append(
        {
            "key": "llm",
            "label": "LLM provider",
            "status": "operational" if llm_configured else "degraded",
            "detail": (
                f"{settings.llm_provider} / {settings.model_name}"
                if llm_configured
                else f"{settings.llm_provider} credential missing"
            ),
        }
    )
    calendar_configured = bool(
        settings.google_calendar_client_id
        and settings.google_calendar_client_secret
        and settings.credential_encryption_key
    )
    connected_calendars = (await db.execute(select(func.count()).select_from(GoogleCalendarCredential))).scalar_one()
    components.append(
        {
            "key": "calendar",
            "label": "Google Calendar",
            "status": "operational" if calendar_configured else "degraded",
            "detail": (
                f"Configured; {connected_calendars} connected accounts"
                if calendar_configured
                else "Per-user Calendar OAuth not configured"
            ),
        }
    )
    statuses = {component["status"] for component in components}
    overall_status = "down" if "down" in statuses else "degraded" if "degraded" in statuses else "operational"
    return AdminSystemHealth(
        overall_status=overall_status,
        checked_at=datetime.now(UTC),
        components=components,
    )


@router.get("/ai-management", response_model=AdminAIManagement)
async def get_ai_management(db: AsyncSession = Depends(get_db)) -> AdminAIManagement:
    settings = get_settings()
    provider_keys = {
        "google": settings.google_api_key,
        "groq": settings.groq_api_key,
        "openai": settings.openai_api_key,
        "openrouter": settings.openrouter_api_key,
    }
    granted_permissions = (
        await db.execute(select(func.count()).select_from(AIPermission).where(AIPermission.granted.is_(True)))
    ).scalar_one()
    revoked_permissions = (
        await db.execute(select(func.count()).select_from(AIPermission).where(AIPermission.granted.is_(False)))
    ).scalar_one()
    proactive_suggestions = (
        await db.execute(select(func.count()).select_from(Task).where(Task.source == "proactive"))
    ).scalar_one()
    proactive_accepted = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.source == "proactive",
                Task.status.in_(("pending", "in_progress", "completed")),
            )
        )
    ).scalar_one()
    proactive_dismissed = (
        await db.execute(
            select(func.count()).select_from(Task).where(Task.source == "proactive", Task.status == "dismissed")
        )
    ).scalar_one()
    return AdminAIManagement(
        provider=settings.llm_provider,
        model=settings.model_name,
        temperature=settings.llm_temperature,
        daily_token_budget=await usage_service.get_daily_token_budget(),
        llm_configured=bool(provider_keys[settings.llm_provider]),
        human_confirmation_required=True,
        conversation_consent_required=True,
        granted_permissions=granted_permissions,
        revoked_permissions=revoked_permissions,
        proactive_suggestions=proactive_suggestions,
        proactive_accepted=proactive_accepted,
        proactive_dismissed=proactive_dismissed,
        configured_providers=ai_config_service.configured_providers(),
        model_options=ai_config_service.MODEL_OPTIONS,
    )


@router.patch("/ai-management", response_model=AdminAIManagement)
async def update_ai_management(
    request: UpdateAIConfigurationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AdminAIManagement:
    if request.provider not in ai_config_service.configured_providers():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"API key for {request.provider} is not configured",
        )
    if not ai_config_service.is_supported_model(request.provider, request.model):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported model for the selected provider",
        )
    settings = get_settings()
    previous = {
        "provider": settings.llm_provider,
        "model": settings.model_name,
        "temperature": settings.llm_temperature,
    }
    current = {
        "provider": request.provider,
        "model": request.model,
        "temperature": request.temperature,
    }
    config = await db.get(SystemConfig, "default")
    if config is None:
        config = SystemConfig(id="default")
        db.add(config)
    config.llm_provider = request.provider
    config.model_name = request.model
    config.llm_temperature = request.temperature
    config.updated_by = current_user.id
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.ai_model_changed",
        target_type="ai_configuration",
        target_id=request.model,
        workspace_id=None,
        metadata={"previous": previous, "current": current},
    )
    await db.commit()
    ai_config_service.apply_ai_configuration(request.provider, request.model, request.temperature)
    return await get_ai_management(db)


@router.get("/ai-usage", response_model=AdminAIUsageReport)
async def get_ai_usage(days: int = Query(default=7, ge=1, le=30)) -> AdminAIUsageReport:
    return AdminAIUsageReport.model_validate(await usage_service.get_usage_report(days))


@router.get("/audit-log", response_model=AdminAuditLogPage)
async def list_audit_log(
    q: str | None = None,
    actor_type: str | None = None,
    workspace_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AdminAuditLogPage:
    stmt = select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_user_id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            AuditLog.action.ilike(pattern)
            | AuditLog.target_type.ilike(pattern)
            | AuditLog.target_id.ilike(pattern)
            | User.email.ilike(pattern)
        )
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if workspace_id:
        stmt = stmt.where(AuditLog.workspace_id == workspace_id)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit))).all()
    return AdminAuditLogPage(
        total=total,
        items=[
            AdminAuditLogOut(
                id=record.id,
                workspace_id=record.workspace_id,
                actor_user_id=record.actor_user_id,
                actor_email=actor.email if actor else None,
                actor_display_name=actor.display_name if actor else None,
                actor_type=record.actor_type,
                action=record.action,
                target_type=record.target_type,
                target_id=record.target_id,
                metadata=record.metadata_json,
                ip_address=record.ip_address,
                created_at=record.created_at,
            )
            for record, actor in rows
        ],
    )


@router.patch("/settings/budget", response_model=AdminStats)
async def update_daily_token_budget(
    request: UpdateBudgetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AdminStats:
    await usage_service.set_daily_token_budget(request.daily_token_budget, updated_by=current_user.id)
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.budget_changed",
        target_type="system_config",
        target_id="default",
        workspace_id=None,
        metadata={"daily_token_budget": request.daily_token_budget},
    )
    await db.commit()
    return await get_stats(db)


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserOut]:
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where((User.email.ilike(pattern)) | (User.display_name.ilike(pattern)))
    users = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    return [AdminUserOut.model_validate(u, from_attributes=True) for u in users]


@router.get("/workspaces", response_model=list[AdminWorkspaceSummaryOut])
async def list_organization_workspaces(db: AsyncSession = Depends(get_db)) -> list[AdminWorkspaceSummaryOut]:
    company = await get_or_create_company_workspace(db)
    agent_workspace_count = (
        await db.execute(
            select(func.count())
            .select_from(AgentWorkspace)
            .where(
                AgentWorkspace.organization_workspace_id == company.id,
                AgentWorkspace.status != "archived",
            )
        )
    ).scalar_one()
    await db.commit()
    return [
        AdminWorkspaceSummaryOut(
            id=company.id,
            name=company.name,
            status=company.status,
            agent_workspace_count=agent_workspace_count,
            created_at=company.created_at,
        )
    ]


@router.get("/company", response_model=WorkspaceOut)
async def get_company(db: AsyncSession = Depends(get_db)) -> WorkspaceOut:
    company = await get_or_create_company_workspace(db)
    await db.commit()
    await db.refresh(company)
    return WorkspaceOut.model_validate(company)


@router.post(
    "/workspaces",
    response_model=AdminWorkspaceSummaryOut,
    status_code=status.HTTP_201_CREATED,
)
async def provision_organization_workspace(
    request: AdminOrganizationWorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AdminWorkspaceSummaryOut:
    del request, db, current_user
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This is a single-company application; create a workspace inside the company",
    )


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
async def update_user_role(
    user_id: str,
    request: UpdateRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AdminUserOut:
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")
    user = await _get_user_or_404(user_id, db)
    user.role = request.role
    user.platform_role = "platform_admin" if request.role == "admin" else "user"
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.user_role_changed",
        target_type="user",
        target_id=user.id,
        workspace_id=None,
        metadata={"role": user.role, "platform_role": user.platform_role},
    )
    await db.commit()
    await db.refresh(user)
    return AdminUserOut.model_validate(user, from_attributes=True)


@router.patch("/users/{user_id}/status", response_model=AdminUserOut)
async def update_user_status(
    user_id: str,
    request: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AdminUserOut:
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own status")
    user = await _get_user_or_404(user_id, db)
    user.is_active = request.is_active
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.user_status_changed",
        target_type="user",
        target_id=user.id,
        workspace_id=None,
        metadata={"is_active": user.is_active},
    )
    await db.commit()
    await db.refresh(user)
    return AdminUserOut.model_validate(user, from_attributes=True)


@router.get("/tasks", response_model=list[AdminTaskOut])
async def list_all_tasks(
    workspace_id: str,
    owner_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[AdminTaskOut]:
    await require_support_scope(db, current_user, workspace_id, "personal_data:read")
    stmt = (
        select(Task)
        .options(selectinload(Task.owner), selectinload(Task.conversation))
        .where(Task.workspace_id == workspace_id)
        .order_by(Task.created_at.desc())
    )
    if owner_id:
        stmt = stmt.where(Task.owner_id == owner_id)
    tasks = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    return [
        AdminTaskOut(
            id=t.id,
            workspace_id=t.workspace_id,
            conversation_id=t.conversation_id,
            title=t.title,
            due_at=t.due_at,
            auto_reminder_enabled=t.auto_reminder_enabled,
            priority=t.priority,
            status=t.status,
            source=t.source,
            row_version=t.row_version,
            created_at=t.created_at,
            updated_at=t.updated_at,
            owner_id=t.owner_id,
            owner_email=t.owner.email,
            owner_display_name=t.owner.display_name,
            conversation_label=_conversation_label(t.conversation),
        )
        for t in tasks
    ]


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_admin(
    task_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    await require_support_scope(db, current_user, workspace_id, "personal_data:manage")
    task = (
        await db.execute(select(Task).where(Task.id == task_id, Task.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.personal_task_deleted",
        target_type="task",
        target_id=task.id,
        workspace_id=workspace_id,
        metadata={},
    )
    await reminder_service.remove_task_reminder(task.id)
    await db.delete(task)
    await db.commit()


@router.get("/reminders", response_model=list[AdminReminderOut])
async def list_all_reminders(
    workspace_id: str,
    owner_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[AdminReminderOut]:
    await require_support_scope(db, current_user, workspace_id, "personal_data:read")
    stmt = (
        select(Reminder)
        .options(selectinload(Reminder.owner))
        .where(Reminder.workspace_id == workspace_id)
        .order_by(Reminder.created_at.desc())
    )
    if owner_id:
        stmt = stmt.where(Reminder.owner_id == owner_id)
    reminders = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    return [
        AdminReminderOut(
            id=r.id,
            workspace_id=r.workspace_id,
            task_id=r.task_id,
            calendar_event_id=r.calendar_event_id,
            lead_minutes=r.lead_minutes,
            title=r.title,
            message=r.message,
            due_at=r.due_at,
            fire_at=r.fire_at,
            status=r.status,
            source=r.source,
            created_at=r.created_at,
            updated_at=r.updated_at,
            owner_id=r.owner_id,
            owner_email=r.owner.email if r.owner else None,
            owner_display_name=r.owner.display_name if r.owner else None,
        )
        for r in reminders
    ]


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder_admin(
    reminder_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    await require_support_scope(db, current_user, workspace_id, "personal_data:manage")
    reminder = (
        await db.execute(select(Reminder).where(Reminder.id == reminder_id, Reminder.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if reminder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    if reminder.status == "scheduled":
        reminder_service.remove_scheduler_job(reminder.id)
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.personal_reminder_deleted",
        target_type="reminder",
        target_id=reminder_id,
        workspace_id=workspace_id,
        metadata={},
    )
    await db.delete(reminder)
    await db.commit()


@router.get("/memories", response_model=list[AdminMemoryOut])
async def list_all_memories(
    workspace_id: str,
    owner_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[AdminMemoryOut]:
    await require_support_scope(db, current_user, workspace_id, "personal_data:read")
    stmt = (
        select(Memory)
        .options(selectinload(Memory.owner))
        .where(Memory.workspace_id == workspace_id)
        .order_by(Memory.created_at.desc())
    )
    if owner_id:
        stmt = stmt.where(Memory.owner_id == owner_id)
    memories = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    return [
        AdminMemoryOut(
            id=m.id,
            workspace_id=m.workspace_id,
            category=m.category,
            title=m.title,
            detail=m.detail,
            memory_type=m.memory_type,
            source_conversation_id=m.source_conversation_id,
            source_message_ids=m.source_message_ids or [],
            consent_scope_hash=m.consent_scope_hash,
            sensitivity=m.sensitivity,
            confidence=m.confidence,
            expires_at=m.expires_at,
            last_accessed_at=m.last_accessed_at,
            created_at=m.created_at,
            updated_at=m.updated_at,
            owner_id=m.owner_id,
            owner_email=m.owner.email,
            owner_display_name=m.owner.display_name,
        )
        for m in memories
    ]


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_admin(
    memory_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    await require_support_scope(db, current_user, workspace_id, "personal_data:manage")
    memory = (
        await db.execute(select(Memory).where(Memory.id == memory_id, Memory.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    await record_audit_event(
        db,
        actor=current_user,
        action="platform.personal_memory_deleted",
        target_type="memory",
        target_id=memory.id,
        workspace_id=workspace_id,
        metadata={},
    )
    await db.delete(memory)
    await db.commit()
