import json
from unittest.mock import Mock

import app  # noqa: F401

from faable.anthropic_compat import (
    anthropic_message_from_events,
    build_responses_payload_from_anthropic,
    iter_anthropic_stream,
)


def _decode(stream) -> list[str]:
    return [event.decode() if isinstance(event, bytes) else event for event in stream]


def _data(event: str) -> dict:
    return json.loads(event.split("\ndata: ", 1)[1])


def test_anthropic_payload_converts_messages_tools_and_history() -> None:
    payload = {
        "model": "chatgpt-gpt-5.6",
        "max_tokens": 512,
        "system": "Be concise.",
        "tools": [{"name": "shell", "description": "Run shell", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "auto"},
        "messages": [
            {"role": "user", "content": "List files"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "shell", "input": {"cmd": "ls"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "a.txt"},
                {"type": "text", "text": "Thanks"},
            ]},
        ],
    }

    upstream = build_responses_payload_from_anthropic(payload)

    assert upstream["model"] == "gpt-5.6-terra"
    assert upstream["instructions"] == "Be concise."
    assert upstream["max_output_tokens"] == 512
    assert upstream["tools"] == [{
        "type": "function",
        "name": "shell",
        "description": "Run shell",
        "parameters": {"type": "object"},
    }]
    assert upstream["tool_choice"] == "auto"
    assert upstream["input"][0] == {"role": "user", "content": [{"type": "input_text", "text": "List files"}]}
    assert upstream["input"][1] == {
        "type": "function_call",
        "call_id": "toolu_1",
        "name": "shell",
        "arguments": "{\"cmd\": \"ls\"}",
    }
    assert upstream["input"][2] == {
        "type": "function_call_output",
        "call_id": "toolu_1",
        "output": "a.txt",
    }
    assert upstream["input"][3] == {"role": "user", "content": [{"type": "input_text", "text": "Thanks"}]}


def test_anthropic_payload_converts_base64_image() -> None:
    payload = {
        "model": "chatgpt-gpt-5.6",
        "max_tokens": 64,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}},
            ],
        }],
    }

    upstream = build_responses_payload_from_anthropic(payload)

    assert upstream["input"][0]["content"] == [
        {"type": "input_text", "text": "What is this?"},
        {"type": "input_image", "image_url": "data:image/png;base64,aGk="},
    ]


def test_anthropic_message_from_events_aggregates_text_and_tool_use() -> None:
    events = [
        {"type": "response.output_text.delta", "delta": "Đang kiểm tra"},
        {"type": "response.output_item.done", "item": {
            "type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "shell", "arguments": "{\"cmd\":\"ls\"}",
        }},
        {"type": "response.completed", "response": {
            "status": "completed",
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        }},
    ]

    result = anthropic_message_from_events(events, "chatgpt-gpt-5.6")

    assert result["type"] == "message"
    assert result["role"] == "assistant"
    assert result["stop_reason"] == "tool_use"
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 8}
    assert result["content"][0] == {"type": "text", "text": "Đang kiểm tra"}
    assert result["content"][1] == {"type": "tool_use", "id": "call_1", "name": "shell", "input": {"cmd": "ls"}}


def test_anthropic_message_from_events_text_only_end_turn() -> None:
    events = [
        {"type": "response.output_text.delta", "delta": "Xin chào"},
        {"type": "response.completed", "response": {"status": "completed"}},
    ]

    result = anthropic_message_from_events(events, "chatgpt-gpt-5.6")

    assert result["stop_reason"] == "end_turn"
    assert result["content"] == [{"type": "text", "text": "Xin chào"}]


def test_anthropic_stream_emits_full_event_sequence() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_text.delta","delta":"Hello"}',
        b'data: {"type":"response.output_item.added","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"shell","arguments":""}}',
        b'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{\\"cmd\\":\\"ls\\"}"}',
        b'data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"shell","arguments":"{\\"cmd\\":\\"ls\\"}"}}',
        b'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":5,"output_tokens":2,"total_tokens":7}}}',
    ]

    events = _decode(iter_anthropic_stream(response, "chatgpt-gpt-5.6"))

    # The text block stop and the tool block start are flushed in one SSE write.
    kinds = [event.split("\n", 1)[0].removeprefix("event: ") for event in events]
    assert kinds == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert all(event.endswith("\n\n") for event in events)
    response.close.assert_called_once()

    start_message = _data(events[0])
    assert start_message["message"]["role"] == "assistant"
    assert start_message["message"]["stop_reason"] is None

    text_start = _data(events[1])
    assert text_start["index"] == 0
    assert text_start["content_block"]["type"] == "text"
    text_delta = _data(events[2])
    assert text_delta["delta"] == {"type": "text_delta", "text": "Hello"}
    assert json.loads(events[3].split("data: ")[1].split("\n\n")[0])["type"] == "content_block_stop"

    tool_start = _data(events[3].split("\n\n", 1)[1])
    assert tool_start["index"] == 1
    assert tool_start["content_block"] == {"type": "tool_use", "id": "call_1", "name": "shell", "input": {}}
    tool_delta = _data(events[4])
    assert tool_delta["index"] == 1
    assert tool_delta["delta"] == {"type": "input_json_delta", "partial_json": "{\"cmd\":\"ls\"}"}
    assert _data(events[5])["index"] == 1

    message_delta = _data(events[6])
    assert message_delta["delta"]["stop_reason"] == "tool_use"
    assert message_delta["usage"] == {"output_tokens": 2}


def test_anthropic_stream_tool_call_without_added_event() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_2","call_id":"call_2","name":"shell","arguments":"{\\"cmd\\":\\"ls\\"}"}}',
        b'data: {"type":"response.completed"}',
    ]

    events = _decode(iter_anthropic_stream(response, "chatgpt-gpt-5.6"))

    kinds = [event.split("\n", 1)[0].removeprefix("event: ") for event in events]
    assert kinds == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    tool_start = _data(events[1])
    assert tool_start["content_block"]["id"] == "call_2"
    tool_delta = _data(events[2])
    assert tool_delta["delta"]["partial_json"] == "{\"cmd\":\"ls\"}"
    assert _data(events[4])["delta"]["stop_reason"] == "tool_use"


def test_anthropic_stream_error_event() -> None:
    response = Mock()
    response.iter_lines.return_value = [
        b'data: {"type":"response.failed","error":{"message":"upstream failed"}}',
    ]

    events = _decode(iter_anthropic_stream(response, "chatgpt-gpt-5.6"))

    error_event = _data(events[1])
    assert error_event == {"type": "error", "error": {"type": "api_error", "message": "upstream failed"}}
    assert events[-1].split("\n", 1)[0].removeprefix("event: ") == "error"


def test_v1_messages_route_end_to_end(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import app
    from faable import app as runtime

    original_key = runtime.GATEWAY_API_KEY
    runtime.GATEWAY_API_KEY = "gateway-secret"

    def fake_upstream_request(payload):
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = [
            b'data: {"type":"response.output_text.delta","delta":"Xin chao"}',
            b'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
        ]
        return response

    monkeypatch.setattr(runtime, "upstream_request", fake_upstream_request)
    try:
        response = TestClient(app).post(
            "/v1/messages",
            headers={"x-api-key": "gateway-secret"},
            json={"model": "chatgpt-gpt-5.6", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        runtime.GATEWAY_API_KEY = original_key

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["content"] == [{"type": "text", "text": "Xin chao"}]
    assert body["stop_reason"] == "end_turn"


def test_v1_messages_invalid_key_returns_anthropic_error() -> None:
    from fastapi.testclient import TestClient

    from app import app

    response = TestClient(app).post(
        "/v1/messages",
        headers={"x-api-key": "wrong-key"},
        json={"model": "chatgpt-gpt-5.6", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "authentication_error"
