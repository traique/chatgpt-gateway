from unittest.mock import Mock

import pytest

from app import classify_device_auth_response, parse_device_auth_payload
from faable import app as runtime


def make_response(status_code: int, headers: dict[str, str], payload: object = None, text: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = headers
    response.text = text
    response.json.return_value = payload
    return response


def test_parse_device_auth_payload_rejects_non_json_response() -> None:
    response = Mock()
    response.status_code = 200
    response.headers = {"content-type": "text/html"}
    response.text = "<html><body>Just a moment...</body></html>"
    response.json.side_effect = ValueError("invalid json")

    with pytest.raises(ValueError, match="non-JSON.*HTTP 200"):
        parse_device_auth_payload(response)


def test_classify_device_auth_response_accepts_pending_error() -> None:
    response = make_response(403, {"content-type": "application/json"}, {"error": {"code": "deviceauth_authorization_pending"}})
    assert classify_device_auth_response(response) == ("pending", None)


def test_classify_device_auth_response_rejects_cloudflare_challenge() -> None:
    response = make_response(403, {"content-type": "text/html", "cf-mitigated": "challenge"}, text="<html>challenge</html>")
    status, message = classify_device_auth_response(response)
    assert status == "failed"
    assert message is not None
    assert "Cloudflare challenge" in message


def test_classify_device_auth_response_rejects_explicit_authorization_error() -> None:
    response = make_response(403, {"content-type": "application/json"}, {"error": {"code": "access_denied", "message": "Device authorization denied."}})
    status, message = classify_device_auth_response(response)
    assert status == "failed"
    assert message == "Device authorization denied."


def test_faable_runtime_uses_patched_device_poll_route() -> None:
    routes = [route for route in runtime.app.routes if getattr(route, "path", None) == "/auth/device/poll" and "POST" in getattr(route, "methods", set())]
    assert len(routes) == 1
    assert routes[0].endpoint.__module__ == "faable.device_auth_patch"


def test_chat_completions_payload_preserves_system_and_message_structure() -> None:
    payload = {"model": "chatgpt-gpt-5.6", "messages": [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}], "stream": False}
    upstream = runtime.build_chat_completions_payload(payload)
    assert upstream == {"model": "gpt-5.6", "instructions": "Be concise.", "store": False, "stream": True, "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}, {"role": "assistant", "content": [{"type": "output_text", "text": "Hi"}]}]}


def test_chat_completions_payload_preserves_image_url() -> None:
    payload = {"model": "gpt-5.6", "messages": [{"role": "user", "content": [{"type": "text", "text": "What is this?"}, {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}}]}]}
    upstream = runtime.build_chat_completions_payload(payload)
    assert upstream["input"][0]["content"] == [{"type": "input_text", "text": "What is this?"}, {"type": "input_image", "image_url": "https://example.com/a.jpg"}]


def test_upstream_error_drains_stream_body() -> None:
    response = make_response(400, {"content-type": "application/json"}, text='{"error":"invalid_request"}')
    response.iter_content.return_value = [b'{"error":"invalid_request"}']
    with pytest.raises(runtime.HTTPException) as error:
        runtime.upstream_response(response)
    assert error.value.status_code == 400
    assert "invalid_request" in str(error.value.detail)
    response.iter_content.assert_called_once()


def test_non_stream_chat_response_aggregates_responses_sse() -> None:
    response = make_response(200, {"content-type": "text/event-stream"})
    response.iter_lines.return_value = [b'data: {"type":"response.output_text.delta","delta":"Hello"}', b'data: {"type":"response.output_text.delta","delta":" world"}', b'data: {"type":"response.completed"}']
    result = runtime.aggregate_chat_completion(response, "chatgpt-gpt-5.6", "gpt-5.6")
    assert result["object"] == "chat.completion"
    assert result["model"] == "chatgpt-gpt-5.6"
    assert result["choices"][0]["message"]["content"] == "Hello world"
    response.iter_lines.assert_called_once()
