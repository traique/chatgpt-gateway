from __future__ import annotations

import faable.app as runtime
from faable.anthropic_compat import (
    anthropic_message_from_events,
    build_responses_payload_from_anthropic,
    iter_anthropic_stream,
)
from faable.anthropic_compat import install as install_anthropic_compat
from faable.device_auth_patch import (
    classify_device_auth_response,
    parse_json_payload as parse_device_auth_payload,
)
from faable.device_auth_patch import install as install_device_auth_patch
from faable.openai_compat import install as install_openai_compat
from faable.provider_routing import install as install_provider_routing

app = runtime.app

install_device_auth_patch(runtime)
install_openai_compat(runtime)
install_anthropic_compat(runtime)
install_provider_routing(runtime)

__all__ = [
    "app",
    "anthropic_message_from_events",
    "build_responses_payload_from_anthropic",
    "classify_device_auth_response",
    "iter_anthropic_stream",
    "parse_device_auth_payload",
]
