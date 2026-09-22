from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.db import session as db_session
from src.db.models import Conversation, Task
from src.services import proactive_service


@pytest.fixture(autouse=True)
def _disable_route_background_tasks(monkeypatch):
    """Message setup must not run the real proactive/event workers before each test's mock."""
    monkeypatch.setattr(
        "starlette.background.BackgroundTasks.add_task",
        lambda self, func, *args, **kwargs: None,
    )


def _fake_llm(*responses: str) -> AsyncMock:
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        SimpleNamespace(content=response, usage_metadata={}) for response in responses
    ]
    return llm


async def _create_conversation(client, creator_headers, other_headers):
    creator = (await client.get("/api/v1/auth/me", headers=creator_headers)).json()
    other = (await client.get("/api/v1/auth/me", headers=other_headers)).json()
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Proactive test team"},
            headers=creator_headers,
        )
    ).json()
    add_member = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": other["email"], "role": "member"},
        headers=creator_headers,
    )
    assert add_member.status_code == 201
    response = await client.post(
        "/api/v1/conversations",
        json={
            "type": "direct",
            "participant_ids": [other["id"]],
            "workspace_id": workspace["id"],
        },
        headers=creator_headers,
    )
    assert response.status_code == 200
    return response.json()["id"], workspace["id"], creator, other


async def _grant_ai(client, conversation_id, headers):
    response = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-permission",
        json={"granted": True, "contribution_allowed": True},
        headers=headers,
    )
    assert response.status_code == 200


async def _send(client, conversation_id, headers, content: str) -> dict:
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"relevant": false}', False),
        ('```json\n{"relevant": true}\n```', True),
        ("not-json", True),
        (None, True),
    ],
)
def test_parse_relevant_fails_open_except_explicit_false(raw, expected):
    assert proactive_service._parse_relevant(raw) is expected


def test_verify_owner_matches_display_name_without_suffix():
    window = [
        (SimpleNamespace(sender_id="u1", content="Mai 8h họp nhé"), SimpleNamespace(display_name="An")),
        (SimpleNamespace(sender_id="u2", content="Tôi đồng ý"), SimpleNamespace(display_name="Quỳnh (Demo)")),
    ]

    owner_id = proactive_service._verify_owner(
        {"name": "Quỳnh", "evidence": "confirmed", "message_index": 2},
        window=window,
        roster={"An": "u1", "Quỳnh (Demo)": "u2"},
        eligible_ids={"u1", "u2"},
        proposal_idx=1,
        is_direct=True,
    )

    assert owner_id == "u2"


def test_verify_owner_rejects_unnamed_group_invitation():
    window = [
        (
            SimpleNamespace(sender_id="u1", content="Mai 8h mọi người đi ăn nhé"),
            SimpleNamespace(display_name="An"),
        )
    ]

    owner_id = proactive_service._verify_owner(
        {"name": "Quỳnh", "evidence": "invited", "message_index": 1},
        window=window,
        roster={"An": "u1", "Quỳnh": "u2"},
        eligible_ids={"u1", "u2"},
        proposal_idx=1,
        is_direct=False,
    )

    assert owner_id is None


@pytest.mark.asyncio
async def test_maybe_suggest_task_skips_when_sender_has_not_granted_ai(
    client, auth_headers, other_auth_headers, monkeypatch
):
    llm = _fake_llm('{"relevant": true}')
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)
    conversation_id, _, creator, _ = await _create_conversation(
        client, auth_headers, other_auth_headers
    )

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=creator["id"],
        content="Mai 8h tôi đi họp",
    )

    llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_relevance_false_skips_window_extraction(
    client, auth_headers, other_auth_headers, monkeypatch
):
    llm = _fake_llm('{"relevant": false}')
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)
    conversation_id, _, creator, _ = await _create_conversation(
        client, auth_headers, other_auth_headers
    )
    await _grant_ai(client, conversation_id, auth_headers)
    message = await _send(client, conversation_id, auth_headers, "Cảm ơn bạn")

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=creator["id"],
        content=message["content"],
        message_id=message["id"],
    )

    assert llm.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_self_commitment_creates_workspace_scoped_task(
    client, auth_headers, other_auth_headers, monkeypatch
):
    conversation_id, workspace_id, creator, _ = await _create_conversation(
        client, auth_headers, other_auth_headers
    )
    await _grant_ai(client, conversation_id, auth_headers)
    message = await _send(client, conversation_id, auth_headers, "Mai 8h tôi đi họp")
    llm = _fake_llm(
        '{"relevant": true}',
        (
            '{"commitments":[{"title":"Họp sáng mai","due_at":"2026-08-18T08:00:00",'
            '"proposal_message_index":1,"cancelled":false,"owners":['
            f'{{"name":"{creator["display_name"]}","evidence":"self","message_index":1}}]}}]}}'
        ),
    )
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=creator["id"],
        content=message["content"],
        message_id=message["id"],
    )

    async with db_session.async_session_maker() as db:
        task = (await db.execute(select(Task).where(Task.owner_id == creator["id"]))).scalar_one()
    assert task.workspace_id == workspace_id
    assert task.source_message_ids == [message["id"]]
    assert task.consent_scope_hash
    assert task.status == "suggested"


@pytest.mark.asyncio
async def test_confirmation_creates_task_for_the_confirmer(
    client, auth_headers, other_auth_headers, monkeypatch
):
    conversation_id, _, creator, other = await _create_conversation(
        client, auth_headers, other_auth_headers
    )
    await _grant_ai(client, conversation_id, auth_headers)
    await _grant_ai(client, conversation_id, other_auth_headers)
    proposal = await _send(client, conversation_id, auth_headers, "Mai 8h đi họp nhé")
    confirmation = await _send(client, conversation_id, other_auth_headers, "Tôi đồng ý")
    llm = _fake_llm(
        '{"relevant": true}',
        (
            '{"commitments":[{"title":"Họp sáng mai","due_at":null,'
            '"proposal_message_index":1,"cancelled":false,"owners":['
            f'{{"name":"{other["display_name"]}","evidence":"confirmed","message_index":2}}]}}]}}'
        ),
    )
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=other["id"],
        content=confirmation["content"],
        message_id=confirmation["id"],
    )

    async with db_session.async_session_maker() as db:
        task = (await db.execute(select(Task).where(Task.owner_id == other["id"]))).scalar_one()
    assert task.source_message_ids == [proposal["id"], confirmation["id"]]
    assert task.source_sender_id == other["id"]

    revoke = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-permission",
        json={"contribution_allowed": False},
        headers=auth_headers,
    )
    assert revoke.status_code == 200
    accept = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": "pending"},
        headers=other_auth_headers,
    )
    assert accept.status_code == 409
    async with db_session.async_session_maker() as db:
        invalidated = await db.get(Task, task.id)
    assert invalidated.status == "invalidated"
    assert invalidated.invalidated_reason == "source_consent_changed"


@pytest.mark.asyncio
async def test_unnamed_direct_invitation_creates_pending_invite_for_other_user(
    client, auth_headers, other_auth_headers, monkeypatch
):
    conversation_id, _, creator, other = await _create_conversation(
        client, auth_headers, other_auth_headers
    )
    await _grant_ai(client, conversation_id, auth_headers)
    await _grant_ai(client, conversation_id, other_auth_headers)
    proposal = await _send(client, conversation_id, auth_headers, "Mai 8h đi ăn sáng nhé")
    llm = _fake_llm(
        '{"relevant": true}',
        (
            '{"commitments":[{"title":"Ăn sáng cùng nhau","due_at":null,'
            '"proposal_message_index":1,"cancelled":false,"owners":['
            f'{{"name":"{creator["display_name"]}","evidence":"self","message_index":1}},'
            f'{{"name":"{other["display_name"]}","evidence":"invited","message_index":1}}]}}]}}'
        ),
    )
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=creator["id"],
        content=proposal["content"],
        message_id=proposal["id"],
    )

    async with db_session.async_session_maker() as db:
        tasks = (await db.execute(select(Task).order_by(Task.owner_id))).scalars().all()
    assert {task.owner_id for task in tasks} == {creator["id"], other["id"]}
    invite = next(task for task in tasks if task.owner_id == other["id"])
    assert "chưa xác nhận" in invite.title


@pytest.mark.asyncio
async def test_window_excludes_direct_message_from_nonconsenting_author(
    client, auth_headers, other_auth_headers
):
    conversation_id, _, _, _ = await _create_conversation(client, auth_headers, other_auth_headers)
    await _grant_ai(client, conversation_id, auth_headers)
    allowed = await _send(client, conversation_id, auth_headers, "Nội dung được phép")
    await _send(client, conversation_id, other_auth_headers, "Nội dung không được phép")

    async with db_session.async_session_maker() as db:
        conversation = await db.get(Conversation, conversation_id)
        window, _, eligible_ids, _ = await proactive_service._load_window(
            db,
            conversation=conversation,
        )

    assert [message.id for message, _ in window] == [allowed["id"]]
    assert len(eligible_ids) == 1


@pytest.mark.asyncio
async def test_maybe_suggest_task_never_raises_on_llm_error(
    client, auth_headers, other_auth_headers, monkeypatch
):
    conversation_id, _, creator, _ = await _create_conversation(
        client, auth_headers, other_auth_headers
    )
    await _grant_ai(client, conversation_id, auth_headers)
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("boom")
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=creator["id"],
        content="Mai 8h tôi đi họp",
    )


@pytest.mark.asyncio
async def test_cancelled_commitment_retracts_only_unconfirmed_suggestion(
    client, auth_headers, other_auth_headers, monkeypatch
):
    conversation_id, _, creator, _ = await _create_conversation(
        client, auth_headers, other_auth_headers
    )
    await _grant_ai(client, conversation_id, auth_headers)
    proposal = await _send(client, conversation_id, auth_headers, "Mai 8h tôi đi họp")
    cancellation = await _send(client, conversation_id, auth_headers, "Thôi hủy cuộc họp nhé")
    async with db_session.async_session_maker() as db:
        conversation = await db.get(Conversation, conversation_id)
        task = Task(
            workspace_id=conversation.workspace_id,
            owner_id=creator["id"],
            conversation_id=conversation_id,
            title="Họp sáng mai",
            source="proactive",
            source_message_ids=[proposal["id"]],
        )
        db.add(task)
        await db.commit()
    llm = _fake_llm(
        '{"relevant": true}',
        (
            '{"commitments":[{"title":"Họp sáng mai","due_at":null,'
            '"proposal_message_index":1,"cancelled":true,"owners":[]}]}'
        ),
    )
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)

    await proactive_service.maybe_suggest_task(
        conversation_id=conversation_id,
        sender_id=creator["id"],
        content=cancellation["content"],
        message_id=cancellation["id"],
    )

    async with db_session.async_session_maker() as db:
        task = (await db.execute(select(Task))).scalar_one()
    assert task.status == "dismissed"
