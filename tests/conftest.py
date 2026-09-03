import os

os.environ["GATEWAY_API_KEY"] = "test-gateway-key"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "password"
os.environ["CHATGPT_TOKEN_ENCRYPTION_KEY"] = "Z1hVQ2FhRk5lY0JjR2xYc2t3V3R4dVh6a0F5cE1tRkE="

import app as gateway_app

__all__ = ["gateway_app"]
