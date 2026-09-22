import pytest
from langchain_core.messages import AIMessage


class _MemoryAcknowledgementLLM:
    async def ainvoke(self, messages):
        facts = messages[-1].content
        if "sếp" in facts and "cẩn thận" in facts:
            content = (
                "Được, từ giờ tôi sẽ gọi bạn là “sếp”. "
                "Tôi cũng đã ghi nhớ rằng bạn rất cẩn thận trong cách làm việc."
            )
        elif "anh Minh" in facts:
            content = "Được, từ giờ tôi sẽ gọi bạn là “anh Minh”."
        elif "sếp" in facts:
            content = "Được, từ giờ tôi sẽ gọi bạn là “sếp”."
        else:
            content = "Đã ghi nhớ preference bạn vừa chia sẻ."
        return AIMessage(content=content)


@pytest.fixture(autouse=True)
def _mock_memory_acknowledgement_llm(monkeypatch):
    monkeypatch.setattr(
        "src.agents.nodes.personal_memory_response_node.get_llm",
        lambda: _MemoryAcknowledgementLLM(),
    )


@pytest.mark.asyncio
async def test_explicit_preference_is_saved_deterministically_and_acknowledged_naturally(
    client, auth_headers, personal_workspace
):
    response = await client.post(
        "/api/v1/chat",
        json={
            "message": (
                "Tôi là người rất cẩn thận trong cách làm việc, "
                "và hãy gọi tôi là sếp mỗi khi tôi hỏi bạn điều gì đó"
            )
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "gọi bạn là “sếp”" in body["response"]
    assert "rất cẩn thận" in body["response"]

    memories = await client.get("/api/v1/memories", headers=auth_headers)
    assert memories.status_code == 200
    by_title = {item["title"]: item for item in memories.json()}
    assert by_title["Cách xưng hô"]["detail"] == "Gọi người dùng là “sếp”."
    assert by_title["Phong cách làm việc"]["detail"] == (
        "Người dùng rất cẩn thận trong cách làm việc."
    )
    assert all(item["workspace_id"] == personal_workspace["id"] for item in by_title.values())


@pytest.mark.asyncio
async def test_changing_form_of_address_updates_instead_of_duplicating(
    client, auth_headers
):
    first = await client.post(
        "/api/v1/chat", json={"message": "Hãy gọi tôi là sếp"}, headers=auth_headers
    )
    second = await client.post(
        "/api/v1/chat", json={"message": "Từ giờ hãy gọi tôi là anh Minh"}, headers=auth_headers
    )
    assert first.status_code == second.status_code == 200

    memories = (await client.get("/api/v1/memories", headers=auth_headers)).json()
    address = [item for item in memories if item["title"] == "Cách xưng hô"]
    assert len(address) == 1
    assert address[0]["detail"] == "Gọi người dùng là “anh Minh”."


@pytest.mark.asyncio
async def test_saved_preferences_are_injected_for_unrelated_future_work_queries(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    saved = await client.post(
        "/api/v1/chat", json={"message": "Hãy gọi tôi là sếp"}, headers=auth_headers
    )
    assert saved.status_code == 200

    fake = fake_llm_factory([AIMessage(content="Vâng, đây là các task của bạn.")])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)
    response = await client.post(
        "/api/v1/chat", json={"message": "Liệt kê task hôm nay"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert fake.invocations
    system_prompt = str(fake.invocations[0][0].content)
    assert "Trusted personalization settings" in system_prompt
    assert 'Address the user as "sếp" naturally in responses.' in system_prompt
    assert "Cách xưng hô" in system_prompt
    assert "Gọi người dùng là “sếp”" in system_prompt


@pytest.mark.asyncio
async def test_legacy_title_only_preference_category_is_applied_to_personal_agent(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    created = await client.post(
        "/api/v1/memories",
        json={
            "category": "Preference",
            "title": "gọi tôi là sếp",
            "detail": "",
            # Reproduce records created by the old UI before it sent a governed memory type.
            "memory_type": "semantic",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["memory_type"] == "semantic"

    fake = fake_llm_factory([AIMessage(content="Sếp, hôm nay bạn có 2 task.")])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)
    response = await client.post(
        "/api/v1/chat", json={"message": "Liệt kê task hôm nay"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["response"].startswith("Sếp,")
    system_prompt = str(fake.invocations[0][0].content)
    assert 'Address the user as "sếp" naturally in responses.' in system_prompt


@pytest.mark.asyncio
async def test_asking_whether_agent_remembers_address_never_falls_to_semantic_clarification(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    created = await client.post(
        "/api/v1/memories",
        json={"category": "Preference", "title": "gọi tôi là sếp", "detail": ""},
        headers=auth_headers,
    )
    assert created.status_code == 201

    async def semantic_classifier_must_not_run(*args, **kwargs):
        raise AssertionError("A high-confidence Personal Memory lookup must not use semantic fallback")

    monkeypatch.setattr(
        "src.agents.nodes.guardrail_node.domain_classifier_service.classify_domain_request",
        semantic_classifier_must_not_run,
    )
    fake = fake_llm_factory([AIMessage(content="Dạ, em nên gọi anh là sếp ạ.")])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Bạn có nhớ cách xưng hô với tôi không?"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["response"] == "Dạ, em nên gọi anh là sếp ạ."
    assert len(fake.invocations) == 1
    assert 'Address the user as "sếp" naturally in responses.' in str(
        fake.invocations[0][0].content
    )


@pytest.mark.asyncio
async def test_work_style_recall_distinguishes_missing_style_from_other_preferences(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    created = await client.post(
        "/api/v1/memories",
        json={"category": "Preference", "title": "gọi tôi là sếp", "detail": ""},
        headers=auth_headers,
    )
    assert created.status_code == 201

    fake = fake_llm_factory(
        [
            AIMessage(
                content=(
                    "Dạ sếp, em chưa có ghi nhớ cụ thể về cách anh làm việc; "
                    "em đang nhớ cần gọi anh là sếp ạ."
                )
            )
        ]
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Tóm tắt những gì bạn nhớ về cách tôi làm việc"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    answer = response.json()["response"]
    assert answer.startswith("Dạ sếp,")
    prompt = str(fake.invocations[0][0].content)
    assert 'Address the user as "sếp" naturally in responses.' in prompt
    assert "accuracy-focused" not in prompt


@pytest.mark.asyncio
async def test_work_style_recall_is_grounded_then_worded_by_llm(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    saved = await client.post(
        "/api/v1/chat",
        json={"message": "Hãy nhớ tôi là người rất cẩn thận trong cách làm việc"},
        headers=auth_headers,
    )
    assert saved.status_code == 200

    fake = fake_llm_factory(
        [AIMessage(content="Em nhớ anh là người rất cẩn thận trong cách làm việc ạ.")]
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Tóm tắt những gì bạn nhớ về cách tôi làm việc"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    answer = response.json()["response"]
    assert "rất cẩn thận trong cách làm việc" in answer
    prompt = str(fake.invocations[0][0].content)
    assert "The user values careful, accuracy-focused work." in prompt
    assert "Người dùng rất cẩn thận trong cách làm việc" in prompt


@pytest.mark.asyncio
async def test_long_term_preference_is_loaded_in_different_personal_agent_threads(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    created = await client.post(
        "/api/v1/memories",
        json={"category": "Preference", "title": "gọi tôi là sếp", "detail": ""},
        headers=auth_headers,
    )
    assert created.status_code == 201

    fake = fake_llm_factory(
        [
            AIMessage(content="Dạ sếp, em nhớ ạ."),
            AIMessage(content="Dạ sếp, sang cuộc trò chuyện mới em vẫn nhớ ạ."),
        ]
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)

    first = await client.post(
        "/api/v1/chat",
        json={"thread_id": "memory-thread-one", "message": "Bạn nhớ cách xưng hô không?"},
        headers=auth_headers,
    )
    second = await client.post(
        "/api/v1/chat",
        json={"thread_id": "memory-thread-two", "message": "Bạn nhớ cách xưng hô không?"},
        headers=auth_headers,
    )

    assert first.status_code == second.status_code == 200
    assert len(fake.invocations) == 2
    for invocation in fake.invocations:
        prompt = str(invocation[0].content)
        assert 'Address the user as "sếp" naturally in responses.' in prompt


@pytest.mark.asyncio
async def test_personalized_suggestions_opt_out_prevents_memory_prompt_injection(
    client, auth_headers, fake_llm_factory, monkeypatch
):
    saved = await client.post(
        "/api/v1/chat", json={"message": "Hãy gọi tôi là sếp"}, headers=auth_headers
    )
    assert saved.status_code == 200
    profile = await client.patch(
        "/api/v1/auth/me",
        json={"preferences": {"personalized_suggestions": False}},
        headers=auth_headers,
    )
    assert profile.status_code == 200

    fake = fake_llm_factory([AIMessage(content="Hôm nay chúng ta bắt đầu nhé.")])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda *args, **kwargs: fake)
    response = await client.post(
        "/api/v1/chat", json={"message": "Liệt kê task hôm nay"}, headers=auth_headers
    )

    assert response.status_code == 200
    prompt = str(fake.invocations[0][0].content)
    assert 'Address the user as "sếp" naturally in responses.' not in prompt
    assert "Gọi người dùng là “sếp”" not in prompt
