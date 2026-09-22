import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph
from psycopg_pool import AsyncConnectionPool


class CounterState(TypedDict):
    value: int


def _postgres_conninfo(url: str) -> str:
    scheme, separator, rest = url.partition("://")
    return f"{scheme.split('+')[0]}{separator}{rest}"


def _counter_graph(checkpointer):
    builder = StateGraph(CounterState)
    builder.add_node("increment", lambda state: {"value": state["value"] + 1})
    builder.set_entry_point("increment")
    builder.set_finish_point("increment")
    return builder.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
async def test_postgres_checkpoint_survives_reconnection():
    """Exercise real persistence when CI/local development provides a separate test database."""
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    conninfo = _postgres_conninfo(test_database_url)
    thread_id = f"checkpoint-integration-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    first_pool = AsyncConnectionPool(
        conninfo=conninfo, min_size=1, max_size=2, open=False, kwargs={"autocommit": True}
    )
    await first_pool.open()
    try:
        first_saver = AsyncPostgresSaver(first_pool)
        await first_saver.setup()
        result = await _counter_graph(first_saver).ainvoke({"value": 1}, config)
        assert result["value"] == 2
    finally:
        await first_pool.close()

    second_pool = AsyncConnectionPool(
        conninfo=conninfo, min_size=1, max_size=2, open=False, kwargs={"autocommit": True}
    )
    await second_pool.open()
    try:
        second_saver = AsyncPostgresSaver(second_pool)
        saved = await second_saver.aget_tuple(config)
        assert saved is not None
        assert saved.checkpoint["channel_values"]["value"] == 2
        await second_saver.adelete_thread(thread_id)
    finally:
        await second_pool.close()
