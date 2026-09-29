"""
Test Matrix & Prompt Catalog for Harness Reverse Engineering
============================================================
Defines the controlled evaluation sessions across Claude Code and Codex CLI.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ExperimentTask:
    id: str
    name: str
    target_dimension: str
    prompt: str
    claude_args: List[str]
    codex_args: List[str]
    expected_inspection: str


TEST_MATRIX: List[ExperimentTask] = [
    ExperimentTask(
        id="task_01_cold_start",
        name="Cold Start & Initial Injections",
        target_dimension="System Prompt & Base Tools",
        prompt=(
            "Identifique-se formalmente com seu nome e versao interna, e liste sucintamente "
            "as primeiras ferramentas nativas e MCPs que voce tem ativas neste ambiente."
        ),
        claude_args=["--model", "sonnet", "--effort", "high"],
        codex_args=["-m", "gpt-6-luna", "-c", "model_reasoning_effort=\"high\""],
        expected_inspection=(
            "Capturar tamanho e conteúdo integral do system prompt inicial, diretrizes de segurança, "
            "schemas JSON das tools nativas (Bash, Edit, Read, etc.) e headers de beta/telemetria."
        ),
    ),
    ExperimentTask(
        id="task_02_discovery",
        name="Deferred Tools, Skills & MCP Discovery",
        target_dimension="Progressive Tool Disclosure & Skills Catalog",
        prompt=(
            "Verifique se ha skills ou servidores MCP configurados neste projeto ou no ambiente "
            "e descreva como o seu harness controla a descoberta progressiva dessas capacidades."
        ),
        claude_args=["--model", "sonnet", "--effort", "high"],
        codex_args=["-m", "gpt-6-luna", "-c", "model_reasoning_effort=\"high\""],
        expected_inspection=(
            "Analisar como o catálogo de skills (SKILL.md) e servidores MCP são expostos no prompt: "
            "se são truncados ('skill descriptions shortened'), se usam referências lazy (r0) ou endpoints dedicados (/backend-api/ps/mcp)."
        ),
    ),
    ExperimentTask(
        id="task_03_context_engine",
        name="Context Engine & Progressive Environment Feeding",
        target_dimension="Context Injection, Caching & File Ingestion",
        prompt=(
            "Leia o arquivo requirements.txt na raiz deste workspace e resuma o proposito "
            "das bibliotecas instaladas em exatamente 3 tópicos concisos."
        ),
        claude_args=["--model", "sonnet", "--effort", "high"],
        codex_args=["-m", "gpt-6-luna", "-c", "model_reasoning_effort=\"high\""],
        expected_inspection=(
            "Observar como o harness injeta o working tree, arquivos lidos pelo agente, "
            "gerenciamento de cache (prompt-caching-scope, cache_control ephemerality) e turnos subsequentes."
        ),
    ),
    ExperimentTask(
        id="task_04_reasoning_effort",
        name="Reasoning Effort Deep Dive (High Effort)",
        target_dimension="Thinking Protocols & Token Budgeting",
        prompt=(
            "Resolva o seguinte enigma lógico: Três agentes (A, B e C) guardam três chaves (Ouro, Prata e Bronze). "
            "A mente sempre, B mente alternadamente, e C sempre diz a verdade. "
            "A diz: 'B tem a chave de ouro'. B diz: 'C tem a chave de prata'. C diz: 'A tem a chave de bronze'. "
            "Trace detalhadamente cada hipótese lógica antes de determinar com certeza quem tem qual chave."
        ),
        claude_args=["--model", "sonnet", "--effort", "high"],
        codex_args=["-m", "gpt-6-luna", "-c", "model_reasoning_effort=\"high\""],
        expected_inspection=(
            "Desvendar o parâmetro exato de esforço enviado: budget_tokens e thinking blocks no Claude vs "
            "model_reasoning_effort='high' e reasoning_tokens no Codex. Avaliar latência e contagem de tokens de reflexão."
        ),
    ),
]


def print_matrix_table():
    """Prints a terminal-friendly summary table of the matrix."""
    print("=" * 85)
    print(f"{'ID':<22} | {'Dimensão':<30} | {'Modelos & Config':<28}")
    print("-" * 85)
    for task in TEST_MATRIX:
        print(f"{task.id:<22} | {task.target_dimension[:30]:<30} | Claude(Sonnet)+Codex(Luna) [High]")
    print("=" * 85)


if __name__ == "__main__":
    print_matrix_table()
