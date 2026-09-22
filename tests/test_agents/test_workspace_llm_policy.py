from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from src.agents.contracts import AgentProfile, ToolResult, ToolResultStatus
from src.agents.profiles.workspace_llm_policy import verify_high_risk_response


@pytest.mark.asyncio
async def test_verifier_is_skipped_for_non_optimistic_business_states(monkeypatch):
    monkeypatch.setattr(
        "src.agents.profiles.workspace_llm_policy.get_settings",
        lambda: SimpleNamespace(workspace_agent_verifier_enabled=True),
    )

    result = await verify_high_risk_response(
        profile=AgentProfile.QUALITY_ASSURANCE,
        snapshot=ToolResult(status=ToolResultStatus.SUCCESS),
        candidate_answer="R1 is NOT_READY.",
        authoritative_value="NOT_READY",
    )

    assert result.applied is False
    assert result.passed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("verdict", "passed"), [("PASS", True), ("FAIL", False)])
async def test_ready_response_uses_bounded_independent_verifier(
    monkeypatch, fake_llm_factory, verdict, passed
):
    verifier = fake_llm_factory(
        [
            AIMessage(
                content=verdict,
                usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
            )
        ]
    )
    monkeypatch.setattr(
        "src.agents.profiles.workspace_llm_policy.get_settings",
        lambda: SimpleNamespace(workspace_agent_verifier_enabled=True),
    )
    monkeypatch.setattr(
        "src.agents.profiles.workspace_llm_policy.get_workspace_llm",
        lambda _profile, purpose: verifier,
    )

    result = await verify_high_risk_response(
        profile=AgentProfile.QUALITY_ASSURANCE,
        snapshot=ToolResult(
            status=ToolResultStatus.SUCCESS,
            payload={"assessment": {"release_readiness": "READY"}},
        ),
        candidate_answer="R1 READY.",
        authoritative_value="READY",
    )

    assert result.applied is True
    assert result.passed is passed
    assert result.usage["total_tokens"] == 11
    assert len(verifier.invocations) == 1
    assert "Return exactly PASS" in verifier.invocations[0][0].content
