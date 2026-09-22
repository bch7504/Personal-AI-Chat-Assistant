from collections import Counter

import pytest
from sqlalchemy import func, select

import src.db.session as db_session
from scripts.seed_delivery_demo import (
    DECISION_SPECS,
    DEMO_USERS,
    DEPENDENCY_SPECS,
    GROUP_PARTICIPANTS,
    LINKED_GROUPS,
    MESSAGE_SPECS,
    MILESTONE_SPECS,
    TASK_SPECS,
    seed_demo,
    validate_fixture_spec,
)
from src.db.models import User, Workspace


def test_delivery_demo_models_three_realistic_teams() -> None:
    validate_fixture_spec()

    message_counts = Counter(group_key for _, group_key, *_ in MESSAGE_SPECS)
    task_counts = Counter(task[-2] for task in TASK_SPECS)
    milestone_counts = Counter(milestone[-1] for milestone in MILESTONE_SPECS)

    assert set(GROUP_PARTICIPANTS) == set(LINKED_GROUPS)
    assert all(len(set(participants)) == 5 for participants in GROUP_PARTICIPANTS.values())
    assert all(message_counts[group_key] >= 8 for group_key in LINKED_GROUPS)
    assert all(task_counts[group_key] >= 5 for group_key in LINKED_GROUPS)
    assert all(milestone_counts[group_key] >= 3 for group_key in LINKED_GROUPS)
    assert len(DEPENDENCY_SPECS) == len(LINKED_GROUPS)
    assert len(DECISION_SPECS) == len(LINKED_GROUPS)


def test_every_delivery_task_is_bound_to_a_message_in_the_same_group() -> None:
    message_groups = {message_key: group_key for message_key, group_key, *_ in MESSAGE_SPECS}

    for task in TASK_SPECS:
        owner_key = task[4]
        group_key = task[-2]
        message_key = task[-1]
        assert owner_key in GROUP_PARTICIPANTS[group_key]
        assert message_groups[message_key] == group_key


def test_demo_accounts_cover_lead_member_and_personal_feature_scenarios() -> None:
    """The demo fixture must include every account type exercised by the UI script."""
    assert {"lead", "member", "admin", "outsider"}.issubset(DEMO_USERS)
    assert {"qa_engineer", "qa_automation", "qa_manual", "qa_security", "qa_performance"}.issubset(DEMO_USERS)
    assert len(DEMO_USERS) == 20


@pytest.mark.asyncio
async def test_demo_seed_provisions_one_personal_space_per_user(client, monkeypatch) -> None:
    monkeypatch.setattr("scripts.seed_delivery_demo.async_session_maker", db_session.async_session_maker)

    await seed_demo()
    await seed_demo()

    demo_emails = [account[0] for account in DEMO_USERS.values()]
    async with db_session.async_session_maker() as session:
        demo_user_count = (
            await session.execute(select(func.count(User.id)).where(User.email.in_(demo_emails)))
        ).scalar_one()
        personal_space_count = (
            await session.execute(
                select(func.count(Workspace.id))
                .join(User, User.id == Workspace.personal_owner_user_id)
                .where(Workspace.type == "personal", User.email.in_(demo_emails))
            )
        ).scalar_one()

    assert demo_user_count == len(DEMO_USERS)
    assert personal_space_count == len(DEMO_USERS)
