from collections.abc import Sequence

import pytest

from src.agents.contracts import ToolResultStatus
from src.agents.schemas.delivery import DeliveryPerson
from src.agents.tools.delivery_milestones import get_delivery_milestones
from src.agents.tools.delivery_people import get_delivery_people
from src.services.delivery_workspace_service import DeliveryQueryScope, DeliveryScopeError
from tests.test_agents.test_delivery_tools import _scope


@pytest.mark.asyncio
async def test_milestone_tool_returns_partial_instead_of_inventing_a_milestone():
    checked: list[str] = []

    async def revalidate(resource_id: str) -> None:
        checked.append(resource_id)

    result = await get_delivery_milestones(scope=_scope(), revalidate_resource=revalidate)

    assert checked == ["group-apollo"]
    assert result.status == ToolResultStatus.PARTIAL
    assert result.payload == {"milestones": []}
    assert result.data_gaps == ("MILESTONE_SOURCE_NOT_AVAILABLE",)


class _PeopleRepository:
    def __init__(self, people: Sequence[DeliveryPerson]) -> None:
        self.people = people
        self.scope: DeliveryQueryScope | None = None

    async def resolve_people(
        self, scope: DeliveryQueryScope, *, user_ids: tuple[str, ...]
    ) -> Sequence[DeliveryPerson]:
        self.scope = scope
        assert user_ids == ("assignee-1",)
        return self.people


@pytest.mark.asyncio
async def test_people_tool_returns_minimal_allowlisted_projection_only():
    base_scope = _scope()
    scope = base_scope.model_copy(update={"allowed_person_ids": ("assignee-1",)})
    repository = _PeopleRepository((DeliveryPerson(user_id="assignee-1", display_name="Minh"),))

    async def revalidate(_: str) -> None:
        return None

    result = await get_delivery_people(
        scope=scope,
        repository=repository,
        revalidate_resource=revalidate,
        user_ids=("assignee-1",),
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert result.payload == {"people": [{"user_id": "assignee-1", "display_name": "Minh"}]}
    assert repository.scope is not None and repository.scope.person_ids == ("assignee-1",)


@pytest.mark.asyncio
async def test_people_tool_denies_guessed_or_extra_user_ids_before_repository_call():
    base_scope = _scope()
    scope = base_scope.model_copy(update={"allowed_person_ids": ("assignee-1",)})
    repository = _PeopleRepository(())

    async def revalidate(_: str) -> None:
        return None

    with pytest.raises(DeliveryScopeError, match="outside the Delivery allowlist"):
        await get_delivery_people(
            scope=scope,
            repository=repository,
            revalidate_resource=revalidate,
            user_ids=("other-user",),
        )
    assert repository.scope is None
