"""
MITM Interceptor Proxy for Claude Code CLI and Codex CLI Reverse Engineering
=============================================================================
Sits transparently between CLI harnesses and upstream cloud backends:
1. Intercepts Claude Code calls (/v1/messages) via ANTHROPIC_BASE_URL.
2. Intercepts OpenAI Codex calls (/backend-api/...) via chatgpt_base_url.
3. Dumps pristine request payloads:
   - System prompts
   - Injected tool schemas & MCP stubs
   - Deferred tool / skill discovery definitions
   - Context engine / environmental injections
   - Reasoning parameters (effort, thinking tokens)
4. Forwards to official cloud APIs via httpx and streams responses back to the CLI.
5. Saves parsed metadata & raw payloads in captured/ directory.
"""

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

CAPTURE_DIR = Path(__file__).parent / "captured"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Harness Reverse Engineering MITM Proxy")

# Active test tag/session for grouping captures
current_session: Dict[str, Any] = {
    "test_id": "init",
    "harness": "unknown",
    "turn": 0
}


def set_active_test(test_id: str, harness: str):
    """Sets the active test context for file naming."""
    current_session["test_id"] = test_id
    current_session["harness"] = harness
    current_session["turn"] = 0


def save_capture(category: str, data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> str:
    """Persists captured payload and a summary metadata file."""
    turn = current_session["turn"]
    current_session["turn"] += 1
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{current_session['test_id']}_{current_session['harness']}_{category}_turn{turn}_{timestamp}"
    
    file_path = CAPTURE_DIR / f"{prefix}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    if metadata:
        meta_path = CAPTURE_DIR / f"{prefix}_summary.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
            
    print(f"\n[MITM CAPTURED] Saved {category} payload to: {file_path.name}")
    return str(file_path)


# ---------------------------------------------------------------------------
# 1. Claude Code CLI Interception (/v1/messages)
# ---------------------------------------------------------------------------
@app.post("/v1/messages")
async def intercept_claude_messages(request: Request):
    """Intercepts requests from Claude Code CLI and forwards to api.anthropic.com."""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        payload = {"_raw": raw_body.decode("utf-8", errors="replace")}

    # Extract high-value architectural details
    system_prompt = payload.get("system", "")
    tools = payload.get("tools", [])
    thinking = payload.get("thinking", {})
    context_mgmt = payload.get("context_management", {})
    model = payload.get("model", "")
    messages = payload.get("messages", [])

    # Format system prompt summary if it is a list of blocks
    sys_text_len = 0
    if isinstance(system_prompt, str):
        sys_text_len = len(system_prompt)
    elif isinstance(system_prompt, list):
        sys_text_len = sum(len(b.get("text", "")) for b in system_prompt if isinstance(b, dict))

    summary = {
        "harness": "claude-code",
        "model": model,
        "system_prompt_char_length": sys_text_len,
        "system_prompt_blocks": len(system_prompt) if isinstance(system_prompt, list) else 1,
        "tools_count": len(tools),
        "tool_names": [t.get("name") for t in tools if isinstance(t, dict)],
        "thinking_config": thinking,
        "context_management": context_mgmt,
        "messages_count": len(messages),
        "headers_inspected": {k: v for k, v in request.headers.items() if k.lower().startswith("anthropic") or k.lower().startswith("x-")},
    }

    save_capture("request", payload, summary)

    # Forward to upstream Anthropic API
    upstream_url = "https://api.anthropic.com/v1/messages"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("content-length", None)
    headers.pop("host", None)

    client = httpx.AsyncClient(timeout=180.0)
    
    if payload.get("stream", False):
        upstream_req = client.build_request("POST", upstream_url, headers=headers, content=raw_body)
        upstream_resp = await client.send(upstream_req, stream=True)

        async def stream_generator():
            try:
                full_chunks = []
                async for chunk in upstream_resp.aiter_bytes():
                    full_chunks.append(chunk)
                    yield chunk
                # Log completion usage from chunks if possible
            finally:
                await upstream_resp.aclose()
                await client.aclose()

        resp_headers = dict(upstream_resp.headers)
        resp_headers.pop("content-length", None)
        return StreamingResponse(stream_generator(), status_code=upstream_resp.status_code, headers=resp_headers)
    else:
        resp = await client.post(upstream_url, headers=headers, content=raw_body)
        await client.aclose()
        try:
            resp_json = resp.json()
            save_capture("response", resp_json)
        except Exception:
            pass
        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))


# ---------------------------------------------------------------------------
# 2. OpenAI Codex CLI Interception (/backend-api/...)
# ---------------------------------------------------------------------------
@app.api_route("/backend-api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def intercept_codex_backend(request: Request, path: str):
    """Intercepts requests from Codex CLI to ChatGPT Backend API."""
    raw_body = await request.body()
    payload = None
    if raw_body:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            payload = {"_raw": raw_body.decode("utf-8", errors="replace")}

    # Inspect if this is the LLM call: codex/responses or similar
    if "codex/responses" in path or "responses" in path:
        summary = {
            "harness": "codex-cli",
            "path": path,
            "method": request.method,
            "model": payload.get("model") if payload else None,
            "reasoning_effort": payload.get("reasoning_effort") or payload.get("model_reasoning_effort") if payload else None,
            "tools_count": len(payload.get("tools", [])) if payload and "tools" in payload else 0,
            "messages_count": len(payload.get("messages", [])) if payload and "messages" in payload else 0,
            "headers_inspected": {k: v for k, v in request.headers.items() if "auth" not in k.lower()},
        }
        if payload:
            save_capture("request", payload, summary)
    elif "ps/mcp" in path:
        if payload:
            save_capture("mcp_discovery", payload, {"path": path})

    # Forward upstream to chatgpt.com
    upstream_url = f"https://chatgpt.com/backend-api/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("content-length", None)
    headers.pop("host", None)

    client = httpx.AsyncClient(timeout=180.0)

    if request.headers.get("accept", "").startswith("text/event-stream") or (payload and payload.get("stream", False)):
        upstream_req = client.build_request(request.method, upstream_url, headers=headers, content=raw_body)
        upstream_resp = await client.send(upstream_req, stream=True)

        async def stream_generator():
            try:
                async for chunk in upstream_resp.aiter_bytes():
                    yield chunk
            finally:
                await upstream_resp.aclose()
                await client.aclose()

        resp_headers = dict(upstream_resp.headers)
        resp_headers.pop("content-length", None)
        return StreamingResponse(stream_generator(), status_code=upstream_resp.status_code, headers=resp_headers)
    else:
        resp = await client.request(request.method, upstream_url, headers=headers, content=raw_body)
        await client.aclose()
        if "codex/responses" in path and resp.status_code == 200:
            try:
                save_capture("response", resp.json())
            except Exception:
                pass
        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))


# Session management endpoint
@app.post("/control/set_session")
async def control_set_session(request: Request):
    data = await request.json()
    set_active_test(data.get("test_id", "test"), data.get("harness", "unknown"))
    return {"status": "ok", "current_session": current_session}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mitm-interceptor", "captured_count": len(list(CAPTURE_DIR.glob("*.json")))}


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9300
    print(f"🚀 Starting MITM Interceptor Proxy on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
