import app  # noqa: F401
from unittest.mock import Mock

from faable import app as runtime
from faable.openai_compat import build_openai_chat_payload, iter_openai_chat_stream


def test_openai_chat_payload_uses_minimal_codex_schema() -> None:
    payload = {
        "model": "chatgpt-gpt-5.6",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ],
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 256,
    }

    upstream = build_openai_chat_payload(payload)

    assert upstream == {
        "model": "gpt-5.6-terra",
        "instructions": "Be concise.",
        "store": False,
        "stream": True,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
            }
        ],
    }


def test_openai_chat_stream_emits_openai_compatible_chunks() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_text.delta","delta":"Xin"}',
        b'data: {"type":"response.output_text.delta","delta":" chao"}',
        b'data: {"type":"response.completed"}',
    ]

    events = list(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))
    payloads = [event.decode() if isinstance(event, bytes) else event for event in events]

    assert '"object":"chat.completion.chunk"' in payloads[0]
    assert '"role":"assistant"' in payloads[0]
    assert '"content":"Xin"' in payloads[0]
    assert '"content":" chao"' in payloads[1]
    assert payloads[-1] == "data: [DONE]\n\n"
    response.close.assert_called_once()


def test_openai_chat_stream_falls_back_to_completed_output_item() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_item.done","item":{"type":"message","content":[{"type":"output_text","text":"OK"}]}}',
        b'data: {"type":"response.completed"}',
    ]

    events = list(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))
    payloads = [event.decode() if isinstance(event, bytes) else event for event in events]

    assert '"content":"OK"' in payloads[0]
    assert payloads[-1] == "data: [DONE]\n\n"
    response.close.assert_called_once()


def test_openai_chat_stream_closes_response_after_upstream_error() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.failed","error":{"message":"upstream failed"}}',
    ]

    events = list(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))
    payloads = [event.decode() if isinstance(event, bytes) else event for event in events]

    assert "upstream failed" in payloads[0]
    assert payloads[-1] == "data: [DONE]\n\n"
    response.close.assert_called_once()
