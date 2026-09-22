from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import AgentState
from src.db import session as db_session
from src.db.models import User
from src.services.people_intelligence_service import build_relevant_people_context


@tool
async def search_people_context(
    query: str = "",
    limit: int = 5,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Find relevant coworkers using private notes and derived workspace interaction metrics.

    Use this when the user asks about a named coworker, frequent collaborators, follow-ups,
    shared work, or who should be involved. Results are scoped to the authenticated user and
    active workspace and never include another user's private notes.
    """
    user_id = (state or {}).get("user_id")
    workspace_id = (state or {}).get("workspace_id")
    if not user_id or not workspace_id:
        raise ValueError("Authenticated user and workspace context are required")
    async with db_session.async_session_maker() as db:
        owner = await db.get(User, user_id)
        if owner is None or not owner.is_active:
            raise ValueError("Authenticated user is unavailable")
        context = await build_relevant_people_context(
            db,
            owner,
            workspace_id,
            query,
            limit=max(1, min(limit, 5)),
        )
    return context or "Không tìm thấy đồng nghiệp phù hợp trong workspace hiện tại."
