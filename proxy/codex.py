"""Codex subscription transport for the native Responses API."""

import httpx
from fastapi import FastAPI, HTTPException, Request

from .auth import CodexAuth
from .transport import forward


def create_app(client_factory=httpx.AsyncClient):
    app = FastAPI(title="Codex subscription proxy")

    @app.post("/v1/responses")
    async def responses(request: Request):
        body = await request.json()
        try:
            _, token, account, _ = CodexAuth.get_credentials()
        except (RuntimeError, OSError, ValueError):
            raise HTTPException(503, "Codex subscription credentials are unavailable.") from None
        if not token:
            raise HTTPException(503, "A ChatGPT subscription token is required.")
        wants_stream = bool(body.get("stream"))
        body.update(stream=True, store=False)
        body.setdefault("instructions", "")
        headers = {"Authorization": f"Bearer {token}", "chatgpt-account-id": account or "", "Accept": "text/event-stream"}
        return await forward("https://chatgpt.com/backend-api/codex/responses", body, headers, client_factory, collect_response=not wants_stream)

    @app.get("/health")
    async def health():
        return {"provider": "codex", "protocol": "responses", "status": "running"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
