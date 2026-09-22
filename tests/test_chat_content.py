from src.models.chat_content import ATTACHMENT_MARKER, text_only_chat_content


def test_text_only_chat_content_preserves_human_text_and_removes_attachment_payload():
    content = f'{ATTACHMENT_MARKER}{{"name":"agenda.png","dataUrl":"data:image/png;base64,abc"}}'

    assert text_only_chat_content(f"Chốt lịch lúc 9h\n{content}") == "Chốt lịch lúc 9h"


def test_text_only_chat_content_supports_legacy_literal_newline_separator():
    attachment = f'{ATTACHMENT_MARKER}{{"name":"brief.pdf"}}'

    assert text_only_chat_content(f"Xin chào\\n{attachment}") == "Xin chào"


def test_text_only_chat_content_returns_empty_for_attachment_only_message():
    attachment = f'{ATTACHMENT_MARKER}{{"name":"brief.pdf"}}'

    assert text_only_chat_content(attachment) == ""
