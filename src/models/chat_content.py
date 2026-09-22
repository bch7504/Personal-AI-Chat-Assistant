"""Shared limits and parsing helpers for chat text with embedded attachment records."""

ATTACHMENT_MARKER = "[[orbit-attachment]]"
MAX_CHAT_MESSAGE_LENGTH = 5_000_000


def text_only_chat_content(content: str | None) -> str:
    """Remove opaque attachment payloads before content is sent to an LLM.

    The original message remains untouched in storage and websocket responses so clients can
    render or download the attachment. Both real newlines and the legacy literal ``\\n`` separator
    are accepted for compatibility with early versions of the composer.
    """

    normalized = str(content or "").replace("\\n", "\n")
    return "\n".join(
        line for line in normalized.splitlines() if not line.startswith(ATTACHMENT_MARKER)
    ).strip()
