from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

import src.db.session as db_session
from src.db.models import EventCandidate, Message
from src.services import calendar_service, event_extraction_service


async def _create_group(client, manager_headers, member_headers):
    member = (await client.get("/api/v1/auth/me", headers=member_headers)).json()
    workspace = (
        await client.post("/api/v1/workspaces", json={"name": "Group AI"}, headers=manager_headers)
    ).json()
    invited = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=manager_headers,
    )
    assert invited.status_code == 201
    conversation = await client.post(
        "/api/v1/conversations",
        json={
            "type": "group",
            "name": "Project calendar",
            "participant_ids": [member["id"]],
            "workspace_id": workspace["id"],
        },
        headers=manager_headers,
    )
    assert conversation.status_code == 200
    return workspace, conversation.json(), member


@pytest.mark.asyncio
async def test_group_manager_controls_one_ai_policy_and_context_is_continuous(
    client, auth_headers, other_auth_headers, monkeypatch, fake_llm_factory
):
    workspace, conversation, _ = await _create_group(client, auth_headers, other_auth_headers)
    conversation_id = conversation["id"]

    forbidden = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=other_auth_headers,
    )
    assert forbidden.status_code == 403

    enabled = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["mode"] == "group_managed"
    assert enabled.json()["granted"] is True

    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "MANAGER-CONTEXT"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "MEMBER-CONTEXT"},
        headers=other_auth_headers,
    )

    captured = {}
    reply = AIMessage(content="Group answer")
    llm = fake_llm_factory([reply])

    async def ainvoke(messages):
        captured["text"] = "\n".join(str(message.content) for message in messages)
        return reply

    llm.ainvoke = ainvoke
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)
    response = await client.post(
        "/api/v1/chat",
        json={
            "message": "Summarize this",
            "conversation_id": conversation_id,
            "workspace_id": workspace["id"],
        },
        headers=other_auth_headers,
    )
    assert response.status_code == 200
    assert "MANAGER-CONTEXT" in captured["text"]
    assert "MEMBER-CONTEXT" in captured["text"]
    assert response.json()["context_scope"]["coverage"] == 1.0
    assert response.json()["context_scope"]["excluded_participants"] == []


@pytest.mark.asyncio
async def test_incremental_event_extraction_updates_same_suggested_candidate(
    client, auth_headers, other_auth_headers, monkeypatch
):
    _, conversation, _ = await _create_group(client, auth_headers, other_auth_headers)
    conversation_id = conversation["id"]
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    manager = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    async with db_session.async_session_maker() as db:
        first = Message(
            conversation_id=conversation_id,
            sender_id=manager["id"],
            content="Chốt họp dự án ngày 20/8 lúc 9h.",
        )
        db.add(first)
        await db.commit()
        await db.refresh(first)

    responses = [
        SimpleNamespace(
            content=(
                '{"action":"create","target_candidate_id":null,"title":"Họp dự án",'
                '"start_at":"2026-08-20T09:00:00+07:00","end_at":"2026-08-20T10:00:00+07:00",'
                '"location":null,"attendees":[],"confidence":0.95,"missing_fields":[]}'
            ),
            usage_metadata={},
        )
    ]
    llm = AsyncMock()
    llm.ainvoke.side_effect = responses
    monkeypatch.setattr(event_extraction_service, "get_llm", lambda: llm)
    candidate = await event_extraction_service.maybe_extract_event_candidate(
        conversation_id=conversation_id, message_id=first.id
    )
    assert candidate is not None

    async with db_session.async_session_maker() as db:
        second = Message(
            conversation_id=conversation_id,
            sender_id=manager["id"],
            content="Dời cuộc họp đó sang 10h.",
        )
        db.add(second)
        await db.commit()
        await db.refresh(second)

    llm.ainvoke.side_effect = [
        SimpleNamespace(
            content=(
                f'{{"action":"update","target_candidate_id":"{candidate.id}","title":null,'
                '"start_at":"2026-08-20T10:00:00+07:00","end_at":"2026-08-20T11:00:00+07:00",'
                '"location":null,"attendees":[],"confidence":0.97,"missing_fields":[]}'
            ),
            usage_metadata={},
        )
    ]
    updated = await event_extraction_service.maybe_extract_event_candidate(
        conversation_id=conversation_id, message_id=second.id
    )
    assert updated is not None
    assert updated.id == candidate.id
    assert updated.start_at.hour == 10
    assert second.id in updated.source_message_ids

    async with db_session.async_session_maker() as db:
        candidates = list(
            (await db.execute(select(EventCandidate).where(EventCandidate.conversation_id == conversation_id)))
            .scalars()
            .all()
        )
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_confirm_event_candidate_requires_manager_and_writes_calendar_only_after_confirmation(
    client, auth_headers, other_auth_headers, monkeypatch
):
    workspace, conversation, _ = await _create_group(client, auth_headers, other_auth_headers)
    conversation_id = conversation["id"]
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    manager = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    async with db_session.async_session_maker() as db:
        message = Message(conversation_id=conversation_id, sender_id=manager["id"], content="Họp 9h")
        db.add(message)
        await db.flush()
        from src.services.consent_service import get_consent_scope_hash

        scope_hash = await get_consent_scope_hash(db, conversation_id)
        candidate = EventCandidate(
            workspace_id=workspace["id"],
            conversation_id=conversation_id,
            operation="create",
            title="Họp dự án",
            start_at=datetime.fromisoformat("2099-08-20T09:00:00+07:00"),
            end_at=datetime.fromisoformat("2099-08-20T10:00:00+07:00"),
            confidence=0.95,
            source_message_ids=[message.id],
            authorization_scope_hash=scope_hash,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

    create = AsyncMock()
    monkeypatch.setattr(calendar_service, "authorize_calendar_access", AsyncMock())
    monkeypatch.setattr(calendar_service, "create_event", lambda *args: {
        "id": "google-1", "summary": "Họp dự án",
        "start": {"dateTime": "2099-08-20T09:00:00+07:00"},
        "end": {"dateTime": "2099-08-20T10:00:00+07:00"},
    })
    monkeypatch.setattr(calendar_service, "broadcast_change", create)

    denied = await client.post(
        f"/api/v1/calendar/candidates/{candidate.id}/confirm", headers=other_auth_headers
    )
    assert denied.status_code == 403
    confirmed = await client.post(
        f"/api/v1/calendar/candidates/{candidate.id}/confirm",
        json={"create_reminder": True, "reminder_lead_minutes": 60},
        headers=auth_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["calendar_event_id"] == "google-1"
    assert confirmed.json()["calendar_owner_user_id"] == manager["id"]
    reminders = (await client.get("/api/v1/reminders", headers=auth_headers)).json()
    linked = next(item for item in reminders if item["calendar_event_id"] == "google-1")
    assert linked["source"] == "proactive"
    assert linked["lead_minutes"] == 60
    assert linked["fire_at"].startswith("2099-08-20T08:00:00")


@pytest.mark.asyncio
async def test_event_backfill_cursor_processes_bounded_batches(
    client, auth_headers, other_auth_headers, monkeypatch
):
    _, conversation, _ = await _create_group(client, auth_headers, other_auth_headers)
    conversation_id = conversation["id"]
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    manager = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    async with db_session.async_session_maker() as db:
        db.add_all([
            Message(conversation_id=conversation_id, sender_id=manager["id"], content="Họp ngày mai"),
            Message(conversation_id=conversation_id, sender_id=manager["id"], content="Gặp khách hàng 9h"),
            Message(conversation_id=conversation_id, sender_id=manager["id"], content="Dời lịch sang 10h"),
        ])
        await db.commit()
    extractor = AsyncMock(return_value=None)
    monkeypatch.setattr(event_extraction_service, "maybe_extract_event_candidate", extractor)

    first = await event_extraction_service.process_event_backfill_batch(conversation_id, 2)
    second = await event_extraction_service.process_event_backfill_batch(conversation_id, 2)
    assert first == {"status": "idle", "processed": 2, "extracted": 0, "has_more": True}
    assert second == {"status": "completed", "processed": 1, "extracted": 0, "has_more": False}
    assert extractor.await_count == 3


@pytest.mark.asyncio
async def test_disabling_group_ai_invalidates_unconfirmed_event_candidate(
    client, auth_headers, other_auth_headers
):
    workspace, conversation, _ = await _create_group(client, auth_headers, other_auth_headers)
    conversation_id = conversation["id"]
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    manager = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    async with db_session.async_session_maker() as db:
        message = Message(conversation_id=conversation_id, sender_id=manager["id"], content="Họp 9h")
        db.add(message)
        await db.flush()
        from src.services.consent_service import get_consent_scope_hash

        candidate = EventCandidate(
            workspace_id=workspace["id"],
            conversation_id=conversation_id,
            operation="create",
            title="Họp dự án",
            start_at=datetime.fromisoformat("2026-08-20T09:00:00+07:00"),
            end_at=datetime.fromisoformat("2026-08-20T10:00:00+07:00"),
            confidence=0.9,
            source_message_ids=[message.id],
            authorization_scope_hash=await get_consent_scope_hash(db, conversation_id),
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

    disabled = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert disabled.status_code == 200
    response = await client.post(
        f"/api/v1/calendar/candidates/{candidate.id}/confirm", headers=auth_headers
    )
    assert response.status_code == 409
    async with db_session.async_session_maker() as db:
        invalidated = await db.get(EventCandidate, candidate.id)
        assert invalidated.status == "invalidated"
        assert invalidated.invalidated_reason == "group_ai_policy_changed"
