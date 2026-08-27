from fastapi import FastAPI

app = FastAPI(title="ChatGPT Gateway", version="0.4.2")


@app.get("/")
def home() -> dict[str, str]:
    return {"status": "ok", "message": "ChatGPT Gateway"}


@app.get("/auth")
def auth() -> dict[str, str]:
    return {"status": "ok", "message": "Admin authentication endpoint"}


@app.get("/dashboard")
def dashboard() -> dict[str, str]:
    return {"status": "ok", "message": "Dashboard"}


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "runtime": "faable", "transport": "curl_cffi"}
