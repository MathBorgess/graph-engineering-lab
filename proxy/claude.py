"""Claude subscription transport for the native Messages API."""

import httpx
from fastapi import FastAPI, HTTPException, Request

from .auth import ClaudeAuth
from .transport import forward


def create_app(client_factory=httpx.AsyncClient):
    app = FastAPI(title="Claude subscription proxy")

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        try:
            token = ClaudeAuth.get_token()
        except RuntimeError:
            raise HTTPException(503, "Claude subscription credentials are unavailable.") from None
        betas = {"claude-code-20250219", *filter(None, request.headers.get("anthropic-beta", "").split(","))}
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
            "anthropic-beta": ",".join(sorted(betas)),
        }
        return await forward("https://api.anthropic.com/v1/messages", body, headers, client_factory)

    @app.get("/health")
    async def health():
        return {"provider": "claude", "protocol": "messages", "status": "running"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
