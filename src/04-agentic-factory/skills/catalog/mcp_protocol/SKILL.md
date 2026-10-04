---
name: mcp_protocol
description: Specs for MCP tools, stdio transport, and JSON-RPC schema expectations for laya-computer plugins.
triggers:
  - mcp
  - stdio
  - server.py
  - json-rpc
skips:
  - ui
---

# MCP Protocol & Plugin Conventions for laya-computer

## 1. Tool Declaration Contract
Tools must be declared using FastMCP or the standard MCP server decorator:
```python
@srv.tool()
async def tool_name(param: dict) -> dict:
    """Clear docstring describing the static analysis or execution action."""
```

## 2. Input/Output Safety Rules
- Inputs should accept raw `dict` if custom validation and sanitized error responses are required.
- Do not let unhandled Pydantic validation exceptions leak raw internal paths or sensitive tokens.
- Return structured status dictionaries with `schema_version`, `status`, and `issues`.

## 3. Stdio Protocol Testing
To verify an MCP tool over stdio without spinning up a live desktop:
- Run `tests/test_protocol.py` to assert that the tool appears in the server's registered tools list.
- Assert exact tool schema compatibility without invoking side-effects.
