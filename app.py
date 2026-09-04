from __future__ import annotations

import faable.app as runtime
from faable.device_auth_patch import (
    classify_device_auth_response,
    parse_json_payload as parse_device_auth_payload,
)
from faable.device_auth_patch import install as install_device_auth_patch
from faable.openai_compat import install as install_openai_compat

app = runtime.app

install_device_auth_patch(runtime)
install_openai_compat(runtime)

__all__ = ["app", "classify_device_auth_response", "parse_device_auth_payload"]
