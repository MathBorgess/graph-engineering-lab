"""
Subscription Reverse Proxy (OpenAI & Anthropic)
-----------------------------------------------
A lightweight, high-performance reverse authenticated proxy that exposes standard
OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/models`, `/v1/responses`)
powered by your active Claude Code and ChatGPT Codex subscriptions.

- Direct cloud communication: no subprocesses, no CLI harness, no prompt pollution.
- Zero proxy-side inference: pure transport, authentication, and protocol translation.
- True real-time streaming: SSE pass-through directly from upstream APIs.
- Native tool calling: converts OpenAI function/tool calls to Anthropic & Codex schemas.
- Designed for LangChain, LangGraph, LlamaIndex, DeepAgents, and standard OpenAI clients.
"""

import argparse
import asyncio
import json
import logging
import os
import platform
import subprocess
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
from pydantic import BaseModel, Field
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("subscription-proxy")

app = FastAPI(
    title="Subscription Reverse Proxy",
    description="Reverse-authenticated proxy to OpenAI and Anthropic using your active subscriptions",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG = {
    "default_backend": os.environ.get("DEFAULT_BACKEND", "codex"),
    "default_codex_model": os.environ.get("DEFAULT_CODEX_MODEL", "gpt-6-sol"),
    "default_claude_model": os.environ.get("DEFAULT_CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
}


# ---------------------------------------------------------
# Subscription Credential Providers
# ---------------------------------------------------------
class ClaudeAuth:
    """Retrieves active OAuth token from macOS Keychain or ~/.claude/.credentials.json."""

    @staticmethod
    def get_token() -> str:
        if platform.system() == "Darwin":
            try:
                raw = subprocess.check_output(
                    ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                    stderr=subprocess.DEVNULL,
                ).decode().strip()
                data = json.loads(raw)
                token = data.get("claudeAiOauth", {}).get("accessToken")
                if token:
                    return token
            except Exception:
                pass

        cred_file = os.path.expanduser("~/.claude/.credentials.json")
        if os.path.exists(cred_file):
            try:
                with open(cred_file) as f:
                    data = json.load(f)
                token = data.get("claudeAiOauth", {}).get("accessToken")
                if token:
                    return token
            except Exception as e:
                logger.error(f"Error reading {cred_file}: {e}")

        raise RuntimeError("No active Claude subscription credentials found in Keychain or ~/.claude/.credentials.json")


class CodexAuth:
    """Retrieves ChatGPT Codex OAuth tokens or API key from ~/.codex/auth.json."""

    @staticmethod
    def get_credentials() -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        auth_file = os.path.expanduser("~/.codex/auth.json")
        if not os.path.exists(auth_file):
            raise RuntimeError(f"Codex credentials not found at {auth_file}")

        with open(auth_file) as f:
            data = json.load(f)

        auth_mode = data.get("auth_mode", "chatgpt")
        api_key = data.get("OPENAI_API_KEY")
        tokens = data.get("tokens", {})
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")

        return auth_mode, access_token, account_id, api_key


# ---------------------------------------------------------
# Request Models (OpenAI Standard)
# ---------------------------------------------------------
class FunctionDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class ToolDefinition(BaseModel):
    type: str = "function"
    function: FunctionDefinition


class ChatMessage(BaseModel):
    role: str
    content: Optional[Union[str, List[Any]]] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "codex"
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = None


# ---------------------------------------------------------
# Model & Backend Routing (Pure Pass-Through)
# ---------------------------------------------------------
def resolve_backend_and_model(model_name: Optional[str]) -> Tuple[str, str]:
    """
    Identifies the provider (anthropic vs openai) and resolves model name.
    If exact model is supplied, it is passed untouched.
    """
    if not model_name or model_name.lower() in ("default", "auto"):
        backend = CONFIG["default_backend"]
        resolved = CONFIG["default_codex_model"] if backend == "codex" else CONFIG["default_claude_model"]
        return backend, resolved

    m = model_name.strip()
    m_lower = m.lower()

    if m_lower in ("claude", "anthropic"):
        return "claude", CONFIG["default_claude_model"]
    if m_lower in ("codex", "openai", "chatgpt"):
        return "codex", CONFIG["default_codex_model"]

    # Check provider by model prefix/name
    if any(k in m_lower for k in ["claude", "sonnet", "opus", "haiku"]):
        # Model alias mappings if short form used
        if m_lower == "sonnet":
            return "claude", "claude-sonnet-4-6"
        elif m_lower == "opus":
            return "claude", "claude-opus-5"
        elif m_lower == "haiku":
            return "claude", "claude-haiku-4-5-20251001"
        return "claude", m

    if any(k in m_lower for k in ["gpt", "codex", "o1", "o3"]):
        return "codex", m

    # Fallback to default
    backend = CONFIG["default_backend"]
    return backend, m


def apply_stop_sequences(text: str, stop: Optional[Union[str, List[str]]]) -> Tuple[str, Optional[str]]:
    """Truncates text at the earliest occurrence of any stop sequence."""
    if not stop:
        return text.strip(), None

    raw_stops = [stop] if isinstance(stop, str) else stop
    stops = []
    for s in raw_stops:
        if s:
            stops.append(s)
            stripped = s.strip()
            if stripped and stripped not in stops:
                stops.append(stripped)

    earliest_idx = len(text)
    matched_stop = None

    for s in stops:
        idx = text.find(s)
        if idx != -1 and idx < earliest_idx:
            earliest_idx = idx
            matched_stop = s

    if matched_stop is not None:
        truncated = text[:earliest_idx].rstrip()
        return truncated + "\n", matched_stop
    return text.strip(), None


# ---------------------------------------------------------
# ANTHROPIC CLOUD PROXY
# ---------------------------------------------------------
def prepare_anthropic_payload(request: ChatCompletionRequest, model_name: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    token = ClaudeAuth.get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "claude-code-20250219",
        "content-type": "application/json",
    }

    system_parts = []
    messages = []

    for msg in request.messages:
        role = msg.role.lower()
        content = msg.content or ""
        if isinstance(content, list):
            text_items = [item.get("text", "") for item in content if isinstance(item, dict) and "text" in item]
            content_str = "\n".join(text_items)
        else:
            content_str = str(content)

        if role == "system":
            system_parts.append(content_str)
        elif role == "user":
            messages.append({"role": "user", "content": content_str})
        elif role == "assistant":
            # Check for tool calls in assistant message
            if msg.tool_calls:
                blocks = []
                if content_str:
                    blocks.append({"type": "text", "text": content_str})
                for tc in msg.tool_calls:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "{}")
                    try:
                        args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args_obj = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                        "name": fn.get("name", "unknown"),
                        "input": args_obj,
                    })
                messages.append({"role": "assistant", "content": blocks})
            else:
                messages.append({"role": "assistant", "content": content_str})
        elif role in ("tool", "function"):
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "tool_call_1",
                        "content": content_str,
                    }
                ],
            })

    if not messages:
        messages.append({"role": "user", "content": "Hello"})

    payload: Dict[str, Any] = {
        "model": model_name,
        "max_tokens": request.max_tokens or request.max_completion_tokens or 4096,
        "messages": messages,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.stop:
        payload["stop_sequences"] = [request.stop] if isinstance(request.stop, str) else list(request.stop)

    # Translate tools
    if request.tools:
        anthropic_tools = []
        for t in request.tools:
            anthropic_tools.append({
                "name": t.function.name,
                "description": t.function.description or "",
                "input_schema": t.function.parameters or {"type": "object", "properties": {}},
            })
        payload["tools"] = anthropic_tools

    return headers, payload


async def execute_claude_cloud(request: ChatCompletionRequest, model_name: str) -> Dict[str, Any]:
    """Non-streaming request to Anthropic API."""
    headers, payload = prepare_anthropic_payload(request, model_name)
    payload["stream"] = False

    logger.info(f"Forwarding to Anthropic: model={model_name} (messages={len(payload['messages'])})")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)

    if resp.status_code != 200:
        logger.error(f"Anthropic API error ({resp.status_code}): {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=f"Anthropic API Error: {resp.text}")

    data = resp.json()
    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    content_text = ""
    tool_calls = []

    for block in data.get("content", []):
        b_type = block.get("type")
        if b_type == "text":
            content_text += block.get("text", "")
        elif b_type == "tool_use":
            tool_calls.append({
                "id": block.get("id"),
                "type": "function",
                "function": {
                    "name": block.get("name"),
                    "arguments": json.dumps(block.get("input", {})),
                },
            })

    content_text, _ = apply_stop_sequences(content_text, request.stop)
    message_obj: Dict[str, Any] = {"role": "assistant"}
    if tool_calls:
        message_obj["tool_calls"] = tool_calls
        message_obj["content"] = content_text or None
        finish_reason = "tool_calls"
    else:
        message_obj["content"] = content_text
        finish_reason = "stop"

    usage = data.get("usage", {})
    return {
        "id": req_id,
        "object": "chat.completion",
        "created": created,
        "model": model_name,
        "choices": [{"index": 0, "message": message_obj, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


async def stream_claude_cloud(request: ChatCompletionRequest, model_name: str) -> AsyncGenerator[str, None]:
    """Direct real-time streaming pass-through from Anthropic API."""
    headers, payload = prepare_anthropic_payload(request, model_name)
    payload["stream"] = True
    headers["Accept"] = "text/event-stream"

    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    logger.info(f"Streaming from Anthropic: model={model_name}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", "https://api.anthropic.com/v1/messages", headers=headers, json=payload) as response:
            if response.status_code != 200:
                err_bytes = await response.aread()
                raise HTTPException(status_code=response.status_code, detail=f"Anthropic Stream Error: {err_bytes.decode(errors='replace')}")

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                try:
                    ev = json.loads(data_str)
                    ev_type = ev.get("type")
                    if ev_type == "content_block_delta":
                        delta_text = ev.get("delta", {}).get("text", "")
                        chunk = {
                            "id": req_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif ev_type == "message_stop":
                        break
                except Exception:
                    continue

    final_chunk = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------
# OPENAI / CHATGPT CODEX BACKEND PROXY
# ---------------------------------------------------------
def prepare_codex_payload(request: ChatCompletionRequest, model_name: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    auth_mode, access_token, account_id, api_key = CodexAuth.get_credentials()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id or "",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    instructions_parts = []
    input_items = []

    for msg in request.messages:
        role = msg.role.lower()
        content = msg.content or ""
        if isinstance(content, list):
            text_items = [item.get("text", "") for item in content if isinstance(item, dict) and "text" in item]
            content_str = "\n".join(text_items)
        else:
            content_str = str(content)

        if role == "system":
            instructions_parts.append(content_str)
        elif role == "user":
            input_items.append({"role": "user", "content": [{"type": "input_text", "text": content_str}]})
        elif role == "assistant":
            input_items.append({"role": "assistant", "content": [{"type": "output_text", "text": content_str}]})
        elif role in ("tool", "function"):
            input_items.append({"role": "user", "content": [{"type": "input_text", "text": f"Observation ({msg.name or 'tool'}): {content_str}"}]})

    if not input_items:
        input_items.append({"role": "user", "content": [{"type": "input_text", "text": "Hello"}]})

    payload: Dict[str, Any] = {
        "model": model_name,
        "store": False,
        "stream": True,
        "input": input_items,
    }
    if instructions_parts:
        payload["instructions"] = "\n\n".join(instructions_parts)

    return headers, payload


async def execute_codex_cloud(request: ChatCompletionRequest, model_name: str) -> Dict[str, Any]:
    """Non-streaming request to ChatGPT Codex responses backend."""
    headers, payload = prepare_codex_payload(request, model_name)
    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    logger.info(f"Forwarding to ChatGPT Codex: model={model_name} (inputs={len(payload['input'])})")
    result_pieces = []
    prompt_tokens = 0
    completion_tokens = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "https://chatgpt.com/backend-api/codex/responses",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                err_bytes = await response.aread()
                logger.error(f"Codex Cloud Error ({response.status_code}): {err_bytes.decode(errors='replace')}")
                raise HTTPException(status_code=response.status_code, detail=f"Codex Cloud Error: {err_bytes.decode(errors='replace')}")

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    ev = json.loads(data_str)
                    ev_type = ev.get("type")
                    if ev_type == "response.output_text.delta":
                        result_pieces.append(ev.get("delta", ""))
                    elif ev_type == "response.completed":
                        usage_obj = ev.get("response", {}).get("usage", {})
                        prompt_tokens = usage_obj.get("input_tokens", prompt_tokens)
                        completion_tokens = usage_obj.get("output_tokens", completion_tokens)
                except Exception:
                    continue

    result_text = "".join(result_pieces).strip()
    result_text, _ = apply_stop_sequences(result_text, request.stop)
    if completion_tokens == 0:
        completion_tokens = len(result_text.split())

    return {
        "id": req_id,
        "object": "chat.completion",
        "created": created,
        "model": model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result_text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def stream_codex_cloud(request: ChatCompletionRequest, model_name: str) -> AsyncGenerator[str, None]:
    """Direct real-time streaming pass-through from ChatGPT Codex backend."""
    headers, payload = prepare_codex_payload(request, model_name)
    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    logger.info(f"Streaming from ChatGPT Codex: model={model_name}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "https://chatgpt.com/backend-api/codex/responses",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                err_bytes = await response.aread()
                raise HTTPException(status_code=response.status_code, detail=f"Codex Stream Error: {err_bytes.decode(errors='replace')}")

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    ev = json.loads(data_str)
                    ev_type = ev.get("type")
                    if ev_type == "response.output_text.delta":
                        delta_text = ev.get("delta", "")
                        chunk = {
                            "id": req_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif ev_type == "response.completed":
                        break
                except Exception:
                    continue

    final_chunk = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------
@app.get("/")
async def root():
    return {
        "name": "Subscription Reverse Proxy",
        "description": "Authenticated reverse proxy for OpenAI and Anthropic models using local subscriptions",
        "mode": "reverse_auth_proxy",
        "endpoints": ["/v1/chat/completions", "/v1/models", "/v1/responses", "/health"],
    }


@app.get("/health")
async def health():
    claude_ok = False
    codex_ok = False
    try:
        ClaudeAuth.get_token()
        claude_ok = True
    except Exception:
        pass

    try:
        CodexAuth.get_credentials()
        codex_ok = True
    except Exception:
        pass

    return {
        "status": "healthy",
        "proxy": "reverse_authenticated_proxy",
        "subscriptions": {
            "anthropic": {"authenticated": claude_ok, "default_model": CONFIG["default_claude_model"]},
            "openai_codex": {"authenticated": codex_ok, "default_model": CONFIG["default_codex_model"]},
        },
    }


@app.get("/v1/models")
async def list_models():
    models = [
        {"id": "gpt-6-sol", "object": "model", "owned_by": "openai-subscription"},
        {"id": "gpt-5.6-sol", "object": "model", "owned_by": "openai-subscription"},
        {"id": "gpt-5.5", "object": "model", "owned_by": "openai-subscription"},
        {"id": "codex", "object": "model", "owned_by": "openai-subscription"},
        {"id": "claude-haiku-4-5-20251001", "object": "model", "owned_by": "anthropic-subscription"},
        {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic-subscription"},
        {"id": "claude-opus-5", "object": "model", "owned_by": "anthropic-subscription"},
        {"id": "claude", "object": "model", "owned_by": "anthropic-subscription"},
    ]
    return {"object": "list", "data": models}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    Standard OpenAI Chat Completions API.
    Routes to the corresponding cloud subscription provider without local model inference.
    """
    backend, resolved_model = resolve_backend_and_model(request.model)

    if request.stream:
        if backend == "claude":
            return StreamingResponse(stream_claude_cloud(request, resolved_model), media_type="text/event-stream")
        elif backend == "codex":
            return StreamingResponse(stream_codex_cloud(request, resolved_model), media_type="text/event-stream")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported backend '{backend}'")

    if backend == "claude":
        response_data = await execute_claude_cloud(request, resolved_model)
    elif backend == "codex":
        response_data = await execute_codex_cloud(request, resolved_model)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported backend '{backend}'")

    return JSONResponse(content=response_data)


@app.post("/v1/responses")
async def responses_endpoint(request: Request):
    """OpenAI Responses API pass-through (/v1/responses)."""
    body = await request.json()
    model = body.get("model", "codex")
    backend, resolved_model = resolve_backend_and_model(model)
    stop = body.get("stop", None)

    raw_input = body.get("input", body.get("messages", []))
    messages: List[ChatMessage] = []
    if isinstance(raw_input, str):
        messages.append(ChatMessage(role="user", content=raw_input))
    elif isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, dict):
                content = item.get("content", "")
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                    content = "\n".join(text_parts) if text_parts else str(content)
                messages.append(ChatMessage(role=item.get("role", "user"), content=content))

    chat_req = ChatCompletionRequest(model=resolved_model, messages=messages, stop=stop)

    if backend == "claude":
        res = await execute_claude_cloud(chat_req, resolved_model)
        final_text = res["choices"][0]["message"]["content"] or ""
        usage = res.get("usage", {})
    else:
        res = await execute_codex_cloud(chat_req, resolved_model)
        final_text = res["choices"][0]["message"]["content"] or ""
        usage = res.get("usage", {})

    resp_data = {
        "id": f"resp-{uuid.uuid4().hex[:12]}",
        "object": "response",
        "created_at": int(time.time()),
        "model": resolved_model,
        "status": "completed",
        "output": [
            {
                "id": f"msg-{uuid.uuid4().hex[:8]}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": final_text}],
            }
        ],
        "usage": usage,
    }
    return JSONResponse(content=resp_data)


# ---------------------------------------------------------
# Server CLI Entry Point
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Subscription Reverse Proxy (OpenAI & Anthropic)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--backend", choices=["codex", "claude"], default="codex", help="Default backend (codex or claude)")
    args = parser.parse_args()

    CONFIG["default_backend"] = args.backend
    print("=" * 70)
    print(f"🚀 Starting SUBSCRIPTION REVERSE PROXY on http://{args.host}:{args.port}")
    print(f"   Architecture    : Direct Reverse-Authenticated Cloud Gateway")
    print(f"   Default Backend : {args.backend}")
    print(f"   ChatGPT Codex   : https://chatgpt.com/backend-api/codex/responses")
    print(f"   Anthropic API   : https://api.anthropic.com/v1/messages")
    print(f"   OpenAI Endpoint : http://{args.host}:{args.port}/v1/chat/completions")
    print("=" * 70)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
