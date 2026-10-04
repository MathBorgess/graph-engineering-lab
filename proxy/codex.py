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
        
        # O backend ChatGPT codex proíbe role: system no input; movemos para o campo 'instructions'
        system_instructions = []
        clean_input = []
        for item in body.get("input", []):
            if isinstance(item, dict) and item.get("role") in ("system", "developer"):
                content = item.get("content")
                if isinstance(content, str):
                    system_instructions.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("text"):
                            system_instructions.append(part["text"])
            else:
                clean_input.append(item)
        
        existing_instructions = body.get("instructions") or ""
        if system_instructions:
            body["instructions"] = (existing_instructions + "\n\n" + "\n\n".join(system_instructions)).strip()
            body["input"] = clean_input
        else:
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
