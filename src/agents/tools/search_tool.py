from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import AgentState
from src.db import session as db_session
from src.services import consent_service


@tool
async def search_messages(
    query: str,
    max_results: int = 20,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Search consent-authorized messages in the active conversation or, from Personal AI,
    across every currently accessible conversation.

    Use this read-only tool when the user refers to an older message, decision, date, name, or link
    that is not present in the immediate context. The conversation identity is injected by the
    server and cannot be supplied or changed by the model.
    """
    conversation_id = (state or {}).get("conversation_id")
    user_id = (state or {}).get("user_id")
    if not conversation_id and not user_id:
        return "No authenticated conversation history is available to search."
    async with db_session.async_session_maker() as db:
        if conversation_id:
            result = await consent_service.search_authorized_messages(
                db, conversation_id, query, max_results
            )
        else:
            result = await consent_service.search_authorized_messages_for_user(
                db,
                user_id=user_id,
                query=query,
                limit=max_results,
            )
    return result or f"No authorized messages matched '{query}'."
