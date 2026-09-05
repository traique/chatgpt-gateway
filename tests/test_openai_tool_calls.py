import json
from unittest.mock import Mock

import app  # noqa: F401

from faable.openai_compat import _aggregate_chat, build_openai_chat_payload, iter_openai_chat_stream


def _decode(stream) -> list[str]:
    return [event.decode() if isinstance(event, bytes) else event for event in stream]


def _data(payload: str) -> dict:
    return json.loads(payload[len("data: "):])


def test_openai_chat_payload_converts_tool_history() -> None:
    payload = {
        "model": "chatgpt-gpt-5.6",
        "messages": [
            {"role": "user", "content": "List files"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "shell", "arguments": "{\"cmd\":\"ls\"}"},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "a.txt\nb.txt"},
        ],
        "tools": [{
            "type": "function",
            "function": {"name": "shell", "description": "Run shell", "parameters": {"type": "object"}},
        }],
    }

    upstream = build_openai_chat_payload(payload)

    assert upstream["input"][0] == {"role": "user", "content": [{"type": "input_text", "text": "List files"}]}
    assert upstream["input"][1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "shell",
        "arguments": "{\"cmd\":\"ls\"}",
    }
    assert upstream["input"][2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "a.txt\nb.txt",
    }
    assert upstream["tools"] == [{
        "type": "function",
        "name": "shell",
        "description": "Run shell",
        "parameters": {"type": "object"},
    }]


def test_openai_chat_stream_translates_tool_calls() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_item.added","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"shell","arguments":""}}',
        b'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{\\"cmd\\""}',
        b'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":":\\"ls\\"}"}',
        b'data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"shell","arguments":"{\\"cmd\\":\\"ls\\"}"}}',
        b'data: {"type":"response.completed","response":{"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}}',
    ]

    payloads = _decode(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))

    first_tool = _data(payloads[0])
    delta = first_tool["choices"][0]["delta"]["tool_calls"][0]
    assert delta["index"] == 0
    assert delta["id"] == "call_1"
    assert delta["type"] == "function"
    assert delta["function"]["name"] == "shell"
    assert delta["function"]["arguments"] == ""
    arg_chunks = [_data(p) for p in payloads[1:3]]
    assert arg_chunks[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == "{\"cmd\""
    assert arg_chunks[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == ":\"ls\"}"
    final = _data(payloads[3])
    assert final["choices"][0]["finish_reason"] == "tool_calls"
    assert final["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert payloads[-1] == "data: [DONE]\n\n"
    response.close.assert_called_once()


def test_openai_chat_stream_tool_call_without_added_event() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_2","call_id":"call_2","name":"shell","arguments":"{\\"cmd\\":\\"ls\\"}"}}',
        b'data: {"type":"response.completed"}',
    ]

    payloads = _decode(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))

    first = _data(payloads[0])
    delta = first["choices"][0]["delta"]["tool_calls"][0]
    assert delta["id"] == "call_2"
    assert delta["function"]["name"] == "shell"
    assert delta["function"]["arguments"] == "{\"cmd\":\"ls\"}"
    final = _data(payloads[1])
    assert final["choices"][0]["finish_reason"] == "tool_calls"


def test_openai_chat_stream_still_translates_plain_text() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_text.delta","delta":"Xin"}',
        b'data: {"type":"response.output_text.delta","delta":" chao"}',
        b'data: {"type":"response.completed","response":{"usage":{"input_tokens":1,"output_tokens":2,"total_tokens":3}}}',
    ]

    payloads = _decode(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))

    assert '"role":"assistant"' in payloads[0]
    final = _data(payloads[2])
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["usage"]["prompt_tokens"] == 1


def test_openai_chat_stream_error_uses_openai_error_shape() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.failed","error":{"message":"upstream failed"}}',
    ]

    payloads = _decode(iter_openai_chat_stream(response, "chatgpt-gpt-5.6"))

    error_event = _data(payloads[0])
    assert error_event["error"]["type"] == "upstream_error"
    assert error_event["error"]["message"] == "upstream failed"


def test_openai_aggregate_chat_returns_tool_calls_and_usage() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"shell","arguments":"{\\"cmd\\":\\"ls\\"}"}}',
        b'data: {"type":"response.completed","response":{"usage":{"input_tokens":7,"output_tokens":3,"total_tokens":10}}}',
    ]

    result = _aggregate_chat(response, "chatgpt-gpt-5.6")

    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["choices"][0]["message"]["content"] is None
    assert result["choices"][0]["message"]["tool_calls"] == [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "shell", "arguments": "{\"cmd\":\"ls\"}"},
    }]
    assert result["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    response.close.assert_called_once()
