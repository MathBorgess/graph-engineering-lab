"""Agente de Especificação com Claude Sonnet 5.5 (O1, O2, O3).

Responsabilidades:
1. Recebe a especificação funcional de `preflight_plan` e os modelos Pydantic `Plan`,
   SEM ACESSO ao código da implementação do worker.
2. Gera:
   - Testes de aceitação visíveis (incluindo caminhos negativos: step alcançável só por on_failure sai UNREACHABLE_STEP).
   - Implementação de referência mínima (BFS sobre next_step a partir de first_step_id).
   - Propriedades Hypothesis (robustez a qualquer dict, first_step alcançável, invariância com on_failure).
   - Testes ocultos (fora do sandbox do worker) com frases de feedback comportamental sem vazar os testes.
3. Registra modelo (claude-sonnet-5-5), tokens, rota e latência.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from agents.llm_client import invoke_sonnet, LLMCallRecord

SPEC_PROMPT_TEMPLATE = """You are the Senior Specification Engineer of the Agentic Software Factory.
You are tasked with creating a comprehensive, rigorous suite of acceptance tests, a minimal reference implementation, and Hypothesis property tests for the `analyze_preflight_plan` feature in the `laya-computer` MCP server.

Here is the functional specification and data models:
=== MODELS ===
{plan_models_code}

=== SPECIFICATION FOR analyze_preflight_plan(plan_data: dict) -> dict ===
1. Contract & Output Structure:
   Returns dict with:
   - schema_version: 1
   - status: "valid" | "invalid" | "unverified"
   - recommendation: "proceed_to_inspection" | "repair" | "human_review"
   - issues: list of dicts with at least 'code' and 'severity' ('error' or 'review')
   - risk_factors: sorted list of strings
   - checks_run: ["plan_schema", "references", "reachability", "risk_rules"]
   - checks_not_run: ["live_accessibility", "runtime_effects"]

2. Reachability Rules:
   - Normal linear execution starts strictly at plan.first_step_id (or plan.start_step if defined, else steps[0].id).
   - Traversal only follows `step.next_step`.
   - CRITICAL NEGATIVE PATH: A step reachable ONLY through `on_failure` is NOT considered reachable during normal preflight execution! Any step in `plan.steps` that is not reachable via `next_step` chain must be flagged with `code="UNREACHABLE_STEP"`, `severity="error"`, causing `status="invalid"` and `recommendation="repair"`.
   - Cycles in next_step must terminate without infinite loops.

3. Risk Rules:
   - action == "set_value" -> writes_user_data
   - key in dangerous shortcuts or "command" or "terminal" -> destructive_keys
   - step.allow_partial_observation == True -> partial_observation
   - Any risk factor present -> recommendation = "human_review"

You must output valid Python code blocks with clear separation headers:
FILE: reference_implementation.py
FILE: test_visible_acceptance.py
FILE: test_hidden_acceptance.py
FILE: test_hypothesis_properties.py
FILE: hidden_feedback.json
"""


def generate_spec_artifacts(plan_models_code: str) -> Dict[str, Any]:
    """Invoca o Claude Sonnet 5.5 para produzir o pacote formal da especificação."""
    prompt = SPEC_PROMPT_TEMPLATE.format(plan_models_code=plan_models_code)
    system = "You are a world-class formal specification and software testing engineer. Output clean, runnable Python code and JSON without extra chatter."

    record = invoke_sonnet(prompt, system=system)
    content = record.content

    # Parse dos arquivos gerados pelo Sonnet
    artifacts = {}
    current_file = None
    current_lines = []

    for line in content.splitlines():
        match = re.match(r"^(?:###\s*)?FILE:\s*([\w.-]+)", line.strip())
        if match:
            if current_file:
                artifacts[current_file] = "\n".join(current_lines).strip()
            current_file = match.group(1)
            current_lines = []
        elif current_file:
            # Remove cercaduras de código markdown
            if line.strip().startswith("```python") or line.strip().startswith("```json") or (line.strip() == "```" and not current_lines):
                continue
            if line.strip() == "```" and current_file:
                continue
            current_lines.append(line)

    if current_file and current_lines:
        artifacts[current_file] = "\n".join(current_lines).strip()

    return {
        "llm_call": record.to_dict(),
        "artifacts": artifacts,
        "raw_response": content,
    }
