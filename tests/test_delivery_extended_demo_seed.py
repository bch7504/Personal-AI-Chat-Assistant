from collections import Counter

from scripts.seed_delivery_extended_demo import (
    EXTENDED_DECISIONS,
    EXTENDED_DEPENDENCIES,
    EXTENDED_MESSAGES,
    EXTENDED_MILESTONES,
    EXTENDED_TASKS,
    validate_extended_fixture,
)


def test_extended_delivery_fixture_has_realistic_volume_and_status_mix() -> None:
    validate_extended_fixture()

    tasks_by_group = Counter(item["group"] for item in EXTENDED_TASKS)
    statuses = Counter(item["status"] for item in EXTENDED_TASKS)

    assert tasks_by_group == {"apollo": 10, "release34": 10, "customer_portal": 10}
    assert statuses["completed"] >= 6
    assert statuses["blocked"] >= 6
    assert statuses["in_progress"] >= 6
    assert statuses["pending"] >= 3
    assert statuses["suggested"] >= 2
    assert statuses["submitted"] >= 1
    assert statuses["changes_requested"] >= 1
    assert len(EXTENDED_MESSAGES) == 18
    assert len(EXTENDED_MILESTONES) == 6
    assert len(EXTENDED_DEPENDENCIES) == 9
    assert len(EXTENDED_DECISIONS) == 6


def test_extended_fixture_covers_checkpoint_and_evidence_conflicts() -> None:
    qualities = {item.get("quality", "pending") for item in EXTENDED_MILESTONES}
    decision_statuses = {item["status"] for item in EXTENDED_DECISIONS}
    contents = [item["content"] for item in EXTENDED_MESSAGES]

    assert {"pending", "accepted", "rejected"}.issubset(qualities)
    assert {"pending", "decided", "superseded"}.issubset(decision_statuses)
    assert any("ON_TRACK" in content and "chat evidence" in content for content in contents)
