"""Validador de contrato MCP via stdio e checagem de schema FastMCP."""

import json
from pathlib import Path
from typing import List, Optional
try:
    from ..contracts.findings import Issue, ValidationResult
except (ImportError, ValueError):
    from contracts.findings import Issue, ValidationResult


import ast


def extract_mcp_tools_from_worktree(worktree_path: Path) -> List[dict]:
    """Extrai ferramentas declaradas com @srv.tool() ou @mcp.tool() via AST no worktree."""
    server_candidates = [
        worktree_path / "laya_computer" / "server.py",
        worktree_path / "server.py",
    ]
    server_file = next((f for f in server_candidates if f.exists()), None)
    if not server_file:
        return []

    try:
        tree = ast.parse(server_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    tools = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_tool = False
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "tool") or (
                    isinstance(dec, ast.Attribute) and dec.attr == "tool"
                ):
                    is_tool = True
            if is_tool:
                doc = ast.get_docstring(node) or ""
                params = [arg.arg for arg in node.args.args]
                tools.append({
                    "name": node.name,
                    "description": doc,
                    "inputSchema": {"properties": {p: {} for p in params}},
                })
    return tools


def validate_mcp_tool_contract(
    server_tools: List[dict],
    expected_tool_name: str = "preflight_plan",
) -> ValidationResult:
    """Valida se o servidor MCP registra a tool esperada com os campos mínimos de contrato."""
    tool_entry = next((t for t in server_tools if t.get("name") == expected_tool_name), None)

    if not tool_entry:
        return ValidationResult(
            validator_name="mcp_contract_validator",
            status="fail",
            command_or_rule="mcp_tool_registration",
            exit_code=1,
            details=f"A ferramenta MCP obrigatória '{expected_tool_name}' não foi encontrada na lista de tools registradas.",
            requires_interrupt=False,
            issues=[
                Issue(
                    code="MISSING_MCP_TOOL",
                    category="bug",
                    severity="blocker",
                    message=f"Servidor MCP não expõe a tool '{expected_tool_name}'.",
                    suggestion=f"Registrar @srv.tool() async def {expected_tool_name}(plan: dict) -> dict em server.py.",
                )
            ],
        )

    issues: List[Issue] = []
    description = tool_entry.get("description", "").strip()
    if not description:
        issues.append(
            Issue(
                code="EMPTY_TOOL_DOCSTRING",
                category="code_smell",
                severity="blocker",
                message=f"A ferramenta MCP '{expected_tool_name}' não possui docstring / descrição de propósito.",
                suggestion="Adicionar docstring concisa explicando a análise estática sem efeitos de desktop.",
            )
        )

    # Checa schema de entrada
    schema = tool_entry.get("inputSchema", {})
    properties = schema.get("properties", {})
    if "plan" not in properties:
        issues.append(
            Issue(
                code="INVALID_TOOL_SCHEMA",
                category="bug",
                severity="critical",
                message=f"A ferramenta '{expected_tool_name}' deve aceitar o parâmetro 'plan' (dict).",
                suggestion="Ajustar assinatura da função para aceitar 'plan: dict'.",
            )
        )

    status = "fail" if any(i.severity in ("blocker", "critical") for i in issues) else "pass"

    return ValidationResult(
        validator_name="mcp_contract_validator",
        status=status,
        command_or_rule="mcp_tool_registration",
        exit_code=0 if status == "pass" else 1,
        details=f"Tool MCP '{expected_tool_name}' validada. {len(issues)} issue(s) apontada(s).",
        requires_interrupt=False,
        issues=issues,
    )
