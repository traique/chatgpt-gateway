import os
import json
import logging
import requests
from flask import Flask, request, Response, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("chatgpt-gateway")

app = Flask(__name__)

CHATGPT_BACKEND_URL = os.environ.get("CHATGPT_BACKEND_URL", "https://chatgpt.com/backend-api").rstrip("/")
DEFAULT_ACCESS_TOKEN = os.environ.get("CHATGPT_ACCESS_TOKEN", "")
GATEWAY_SECRET = os.environ.get("GATEWAY_SECRET", "")

@app.after_request
def set_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-requested-with, Cookie"
    return response

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "online",
        "service": "ChatGPT Session Gateway",
        "platform": "Faable Deploy"
    }), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

def get_token(req):
    auth_header = req.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
        if GATEWAY_SECRET and bearer_token == GATEWAY_SECRET:
            return DEFAULT_ACCESS_TOKEN
        return bearer_token
    return DEFAULT_ACCESS_TOKEN

@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def chat_completions():
    if request.method == "OPTIONS":
        return Response(status=204)

    token = get_token(request)
    if not token:
        return jsonify({
            "error": "Missing access token. Set CHATGPT_ACCESS_TOKEN env or send Bearer token."
        }), 401

    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages", [])
    model = payload.get("model", "text-davinci-002-render-sha")
    is_stream = payload.get("stream", True)

    chatgpt_payload = {
        "action": "next",
        "messages": [
            {
                "id": "aaa11111-1111-1111-1111-111111111111",
                "author": {"role": msg.get("role", "user")},
                "content": {"content_type": "text", "parts": [msg.get("content", "")]}
            }
            for msg in messages
        ],
        "model": model,
        "parent_message_id": "aaa22222-2222-2222-2222-222222222222"
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/event-stream" if is_stream else "application/json"
    }

    target_url = f"{CHATGPT_BACKEND_URL}/conversation"

    try:
        req_proxy = requests.post(
            target_url,
            headers=headers,
            json=chatgpt_payload,
            stream=is_stream,
            timeout=120
        )

        if is_stream:
            def generate_stream():
                for chunk in req_proxy.iter_lines():
                    if chunk:
                        yield chunk.decode("utf-8") + "\n\n"
            return Response(generate_stream(), content_type="text/event-stream")

        return Response(req_proxy.content, status=req_proxy.status_code, content_type="application/json")

    except Exception as e:
        logger.error(f"Error calling ChatGPT Backend: {e}")
        return jsonify({"error": f"Gateway proxy failed: {str(e)}"}), 502

@app.route("/backend-api/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
def proxy_backend_api(path):
    if request.method == "OPTIONS":
        return Response(status=204)

    token = get_token(request)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}
    
    if token:
        headers["Authorization"] = f"Bearer {token}"

    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    target_url = f"{CHATGPT_BACKEND_URL}/{path}"

    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            stream=True,
            timeout=120
        )
        return Response(resp.iter_content(chunk_size=4096), status=resp.status_code, content_type=resp.headers.get("content-type"))
    except Exception as e:
        logger.error(f"Error forwarding: {e}")
        return jsonify({"error": str(e)}), 502

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
