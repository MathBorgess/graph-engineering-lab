"""Native HTTP forwarding; provider SDKs own tool schemas and streaming deltas."""

import json

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse


async def forward(url, body, headers, client_factory, *, collect_response=False):
    client = client_factory(timeout=60.0)
    try:
        response = await client.send(client.build_request("POST", url, json=body, headers=headers), stream=True)
    except Exception:
        await client.aclose()
        raise
    if response.status_code >= 400:
        status = response.status_code
        err_bytes = await response.aread()
        err_msg = err_bytes.decode("utf-8", errors="replace")
        await response.aclose()
        await client.aclose()
        raise HTTPException(status, f"Upstream request failed ({status}): {err_msg}")

    if collect_response:
        items = []
        try:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("type") == "response.output_item.done" and "item" in event:
                    items.append(event["item"])
                if event.get("type") == "response.completed":
                    resp_dict = event["response"]
                    if not resp_dict.get("output") and items:
                        resp_dict["output"] = items
                    return JSONResponse(resp_dict)
                if event.get("type") in {"error", "response.failed", "response.incomplete"}:
                    raise HTTPException(502, "Upstream response failed or was incomplete.")
            raise HTTPException(502, "Upstream stream ended without response.completed.")
        finally:
            await response.aclose()
            await client.aclose()

    if body.get("stream"):
        async def chunks():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()
        return StreamingResponse(chunks(), media_type="text/event-stream")

    try:
        return JSONResponse(json.loads(await response.aread()))
    finally:
        await response.aclose()
        await client.aclose()
