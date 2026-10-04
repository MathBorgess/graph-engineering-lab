"""Servidor MCP de demonstração para testes de consumo direto pelo deepagents."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("demo_risk_analyzer")


@server.tool()
def calculate_plan_risk(step_count: int, has_destructive_keys: bool) -> dict:
    """Calcula o nível de risco estático de um plano de automação.
    
    Args:
        step_count: Quantidade de passos declarados no plano.
        has_destructive_keys: Se o plano envia teclas como delete ou ctrl+c.
    """
    if has_destructive_keys or step_count > 10:
        return {"risk_level": "high", "requires_hitl": True}
    return {"risk_level": "routine", "requires_hitl": False}


if __name__ == "__main__":
    server.run(transport="stdio")
