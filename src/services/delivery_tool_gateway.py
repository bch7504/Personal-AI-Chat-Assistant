"""Server-side capability gateway for Product Delivery deterministic tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import ToolResult
from src.agents.policies.resource_guard import enforce_agent_resource_access
from src.agents.schemas.delivery import DeliveryItem, DeliveryReadScope
from src.agents.tools.delivery_analysis import (
    get_delivery_decisions,
    get_delivery_dependencies,
    get_delivery_release_status,
)
from src.agents.tools.delivery_messages import search_delivery_messages
from src.agents.tools.delivery_milestones import get_delivery_milestones
from src.agents.tools.delivery_people import get_delivery_people
from src.agents.tools.delivery_tasks import get_delivery_tasks
from src.services.delivery_checkpoint_service import read_delivery_checkpoint_progress
from src.services.delivery_workspace_service import (
    SqlAlchemyDeliveryControlRepository,
    SqlAlchemyDeliveryMessageRepository,
    SqlAlchemyDeliveryMilestoneRepository,
    SqlAlchemyDeliveryPeopleRepository,
    SqlAlchemyDeliveryReleaseRepository,
    SqlAlchemyDeliveryTaskRepository,
)


@dataclass(frozen=True)
class DeliveryToolBundle:
    tasks: ToolResult
    milestones: ToolResult
    messages: ToolResult
    people: ToolResult
    dependencies: ToolResult
    decisions: ToolResult
    releases: ToolResult
    checkpoints: ToolResult


class DeliveryToolGateway:
    """Execute allowlisted Delivery reads with live resource revalidation.

    The model never instantiates this gateway and never supplies its trusted
    context. A caller provides the server-resolved scope produced after RBAC.
    """

    def __init__(self, *, db: AsyncSession, prepared: Any, scope: DeliveryReadScope) -> None:
        self._db = db
        self._prepared = prepared
        self._scope = scope

    async def _revalidate(self, resource_id: str) -> None:
        await enforce_agent_resource_access(
            self._db,
            context=self._prepared.context,
            resource_id=resource_id,
        )

    async def read_tasks(self) -> ToolResult:
        return await get_delivery_tasks(
            scope=self._scope,
            repository=SqlAlchemyDeliveryTaskRepository(self._db),
            revalidate_resource=self._revalidate,
        )

    async def read_bundle(
        self,
        *,
        message: str,
        from_at: datetime,
        to_at: datetime,
    ) -> DeliveryToolBundle:
        tasks = await self.read_tasks()
        milestones = await get_delivery_milestones(
            scope=self._scope,
            revalidate_resource=self._revalidate,
            repository=SqlAlchemyDeliveryMilestoneRepository(self._db),
        )
        messages = await search_delivery_messages(
            scope=self._scope,
            repository=SqlAlchemyDeliveryMessageRepository(self._db),
            revalidate_resource=self._revalidate,
            query=message,
            from_at=from_at,
            to_at=to_at,
            limit=20,
        )
        people = await get_delivery_people(
            scope=self._scope,
            repository=SqlAlchemyDeliveryPeopleRepository(self._db),
            revalidate_resource=self._revalidate,
            user_ids=self._scope.allowed_person_ids,
        )
        control = SqlAlchemyDeliveryControlRepository(self._db)
        dependencies = await get_delivery_dependencies(
            scope=self._scope,
            repository=control,
            revalidate_resource=self._revalidate,
        )
        decisions = await get_delivery_decisions(
            scope=self._scope,
            repository=control,
            revalidate_resource=self._revalidate,
        )
        releases = await get_delivery_release_status(
            scope=self._scope,
            repository=SqlAlchemyDeliveryReleaseRepository(self._db),
            revalidate_resource=self._revalidate,
        )
        for resource_id in self._scope.effective_group_ids:
            await self._revalidate(resource_id)
        checkpoints = await read_delivery_checkpoint_progress(self._db, scope=self._scope)
        return DeliveryToolBundle(
            tasks=tasks,
            milestones=milestones,
            messages=messages,
            people=people,
            dependencies=dependencies,
            decisions=decisions,
            releases=releases,
            checkpoints=checkpoints,
        )

    @staticmethod
    def filter_exact_task(result: ToolResult, task_id: str) -> ToolResult:
        rows = [
            item for item in result.payload.get("items", []) if str(item.get("id", "")).casefold() == task_id.casefold()
        ]
        source_ids = {
            source.get("resource_id") for row in rows for source in row.get("sources", []) if isinstance(source, dict)
        }
        sources = tuple(source for source in result.sources if source.resource_id in source_ids)
        return result.model_copy(
            update={
                "payload": {"items": rows, "query_task_id": task_id, "found": bool(rows)},
                "sources": sources or result.sources,
            }
        )

    @staticmethod
    def normalized_items(result: ToolResult) -> tuple[DeliveryItem, ...]:
        return tuple(DeliveryItem.model_validate(item) for item in result.payload.get("items", []))
