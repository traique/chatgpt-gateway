from unittest.mock import Mock

import pytest

from faable.app import parse_device_auth_payload


def test_parse_device_auth_payload_rejects_non_json_response() -> None:
    response = Mock()
    response.status_code = 200
    response.headers = {"content-type": "text/html"}
    response.text = "<html><body>Just a moment...</body></html>"
    response.json.side_effect = ValueError("invalid json")

    with pytest.raises(ValueError, match="non-JSON.*HTTP 200"):
        parse_device_auth_payload(response)
