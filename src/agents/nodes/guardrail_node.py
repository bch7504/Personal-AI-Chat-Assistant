from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.state import AgentState
from src.services import domain_classifier_service, guardrail_service


def _current_and_previous_turn(state: AgentState) -> tuple[str, str, str]:
    """Return latest user text plus the previous user/assistant turn from checkpoint memory."""
    messages = state.get("messages", [])
    latest_human_index = next(
        (index for index in range(len(messages) - 1, -1, -1) if isinstance(messages[index], HumanMessage)),
        None,
    )
    if latest_human_index is None:
        return "", "", ""

    latest = str(messages[latest_human_index].content)
    previous_user = ""
    previous_assistant = ""
    for message in reversed(messages[:latest_human_index]):
        if not previous_assistant and isinstance(message, AIMessage) and message.content:
            previous_assistant = str(message.content)
        elif isinstance(message, HumanMessage):
            previous_user = str(message.content)
            break
    return latest, previous_user, previous_assistant


async def input_guardrail_node(state: AgentState) -> dict:
    """Block unsafe/out-of-domain requests before the planner can see them."""
    latest, previous_user, previous_assistant = _current_and_previous_turn(state)
    decision = guardrail_service.evaluate_request_with_history(
        latest,
        previous_user_text=previous_user,
        previous_assistant_text=previous_assistant,
        conversation_mode=bool(state.get("conversation_id")),
    )
    # Conversation data is also a trust boundary. Reject hard-sensitive context before even the
    # semantic domain classifier sees the request, preserving the no-LLM path for hard policy.
    # Capability help is a fixed product answer and never reads conversation data. Do not let
    # unrelated content in an open chat turn a harmless "what can you do?" question into a
    # refusal; the deterministic response path receives none of that content.
    if decision.category != "capability_help" and (
        decision.category == "out_of_domain" or decision.allowed
    ):
        if state.get("context"):
            context_decision = guardrail_service.evaluate_context(state["context"])
            if not context_decision.allowed:
                decision = context_decision
    semantic_metadata = None
    if not decision.allowed and decision.category == "out_of_domain":
        semantic = await domain_classifier_service.classify_domain_request(
            latest,
            previous_user_text=previous_user,
            previous_assistant_text=previous_assistant,
            conversation_mode=bool(state.get("conversation_id")),
            user_id=state.get("user_id"),
        )
        semantic_metadata = {
            "decision": semantic.decision,
            "intent": semantic.intent,
            "confidence": semantic.confidence,
            "reason": semantic.reason,
        }
        if semantic.decision == "allow":
            decision = guardrail_service.GuardrailDecision(
                True, f"semantic_{semantic.intent}", semantic.reason, ""
            )
        elif semantic.decision == "clarify":
            question = guardrail_service.sanitize_untrusted_text(
                semantic.clarification_question
            ).strip()
            return {
                "guardrail_blocked": False,
                "guardrail_requires_clarification": True,
                "metadata": {
                    **state.get("metadata", {}),
                    "guardrail": {
                        "allowed": False,
                        "category": "needs_clarification",
                        "intent": semantic.intent,
                        "confidence": semantic.confidence,
                        "reason": semantic.reason,
                    },
                },
                "messages": [AIMessage(content=question)],
            }
        else:
            safe_reason = guardrail_service.sanitize_untrusted_text(semantic.reason).strip()
            decision = guardrail_service.GuardrailDecision(
                False, "out_of_domain", safe_reason,
                (
                    f"Orbit không thể hỗ trợ yêu cầu này vì {safe_reason}. "
                    "Orbit tập trung vào công việc, lịch, nhiệm vụ, memory và phân tích "
                    "các cuộc trò chuyện đã được cấp quyền."
                ),
            )
    metadata = {
        **state.get("metadata", {}),
        "guardrail": {
            "allowed": decision.allowed,
            "category": decision.category,
            "reason": decision.reason,
            **({"semantic": semantic_metadata} if semantic_metadata else {}),
        },
    }
    if decision.allowed:
        return {
            "guardrail_blocked": False,
            "guardrail_requires_clarification": False,
            "metadata": metadata,
        }
    return {
        "guardrail_blocked": True,
        "metadata": metadata,
        "messages": [AIMessage(content=decision.response)],
    }


async def output_guardrail_node(state: AgentState) -> dict:
    """Replace a generated unsafe/leaking response before it reaches the API."""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, (AIMessage, ToolMessage)) and message.content:
            decision = guardrail_service.evaluate_output(str(message.content))
            if not decision.allowed:
                return {
                    "messages": [AIMessage(content=decision.response)],
                    "metadata": {
                        **state.get("metadata", {}),
                        "output_guardrail": {
                            "allowed": False,
                            "category": decision.category,
                            "reason": decision.reason,
                        },
                    },
                }
            break
    return {"metadata": {**state.get("metadata", {}), "output_guardrail": {"allowed": True}}}
