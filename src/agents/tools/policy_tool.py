import json

from langchain_core.tools import tool

from src.services.guardrail_service import evaluate_request


@tool
def check_request_policy(request_text: str) -> str:
    """Check whether an unfamiliar request is inside Orbit's allowed work/chat domain.

    Call this before answering when the request's domain or safety is not evident.
    This tool is advisory for the planner; a deterministic guardrail already blocks
    clear policy violations before the planner runs.

    Args:
        request_text: The user's request verbatim, without reinterpretation.
    """
    decision = evaluate_request(request_text)
    return json.dumps(
        {
            "allowed": decision.allowed,
            "category": decision.category,
            "reason": decision.reason,
            "required_action": "continue" if decision.allowed else "refuse_with_reason",
        },
        ensure_ascii=False,
    )

