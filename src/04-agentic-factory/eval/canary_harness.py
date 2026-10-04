"""Harness de Canários e Verificação de Mutações — Experimento 04 Rodada 3.

Regras Estritas:
1. Pré-registro de hipótese, rota esperada e critério de falha.
2. Mutação comprovada: diff unificado capturado e SHA-256 gravado. Caso com diff vazio é INVALID_RUN.
3. Canários em toda corrida: Controle Limpo (deve passar 100%) + violação plantada por validador.
   Se o controle falhar ou o canário não for pego -> corrida inválida (defeito da esteira).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

WORKTREE_PATH = Path("/Users/matheusborges/github/mcps-catalog-worktree-exp04/laya-computer").resolve()
ROUND3_DIR = FACTORY_DIR / "eval" / "round3"
ROUND3_DIR.mkdir(parents=True, exist_ok=True)

from graph.nodes import validator_node, dod_node


class InvalidMutationError(Exception):
    """Lançada quando uma mutação não produz o diff esperado ou gera diff vazio."""
    pass


class CanaryFailureError(Exception):
    """Lançada quando o controle limpo reprova ou um canário de validador não é capturado."""
    pass


def reset_worktree():
    """Restaura o worktree ao commit limpo da baseline verde."""
    subprocess.run(["git", "checkout", "-f"], cwd=str(WORKTREE_PATH), check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=str(WORKTREE_PATH), check=True, capture_output=True)


def get_worktree_diff() -> Tuple[str, str]:
    """Retorna (diff_str, sha256_hash). Inclui arquivos não rastreados via git status."""
    p_diff = subprocess.run(["git", "diff", "HEAD"], cwd=str(WORKTREE_PATH), capture_output=True, text=True)
    diff_text = p_diff.stdout

    # Se diff estiver vazio, verifica se há untracked files
    p_status = subprocess.run(["git", "status", "--porcelain"], cwd=str(WORKTREE_PATH), capture_output=True, text=True)
    untracked_lines = [l for l in p_status.stdout.splitlines() if l.startswith("??")]
    
    if untracked_lines:
        extra_diff = []
        for line in untracked_lines:
            fpath = line[3:].strip()
            if fpath.startswith(f"{WORKTREE_PATH.name}/"):
                fpath = fpath[len(WORKTREE_PATH.name) + 1:]
            full_p = WORKTREE_PATH / fpath
            if full_p.is_file():
                try:
                    content = full_p.read_text(encoding="utf-8")
                    extra_diff.append(f"--- /dev/null\n+++ b/{fpath}\n@@ -0,0 +1 @@\n+{content}")
                except Exception:
                    extra_diff.append(f"--- /dev/null\n+++ b/{fpath}\n[binary/unreadable]")
        diff_text = (diff_text + "\n" + "\n".join(extra_diff)).strip()

    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
    return diff_text, diff_hash


def verify_mutation_applied(target_file: Path, old_text: str, new_text: str) -> Tuple[str, str]:
    """Aplica substituição estrita exigindo a presença de old_text e validando diff não-vazio."""
    if not target_file.exists():
        raise InvalidMutationError(f"Arquivo alvo não existe: {target_file}")
    
    content = target_file.read_text(encoding="utf-8")
    if old_text not in content:
        raise InvalidMutationError(f"String esperada para mutação não encontrada em {target_file}:\n'{old_text[:100]}'")
    
    new_content = content.replace(old_text, new_text, 1)
    target_file.write_text(new_content, encoding="utf-8")

    diff_text, diff_hash = get_worktree_diff()
    if not diff_text.strip():
        raise InvalidMutationError(f"Mutação em {target_file} resultou em diff vazio!")
    return diff_text, diff_hash


def execute_pipeline(
    case_id: str,
    description: str,
    hypothesis: str,
    expected_route: str,
    failure_criterion: str,
    allowed_patterns: Optional[List[str]] = None,
    raw_memories_file: Optional[Path] = None,
    human_decisions: Optional[List[Dict[str, Any]]] = None,
    diff_text: str = "",
    diff_hash: str = "",
    mutation_verified: bool = True,
    llm_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Executa os validadores e a DoD registrando todas as métricas formais."""
    patterns = allowed_patterns or ["laya_computer/*", "tests/*", "README.md", "pyproject.toml"]
    
    state = {
        "worktree_path": str(WORKTREE_PATH),
        "affected_files": [],
        "feature_name": "preflight_plan",
        "raw_memories_path": str(raw_memories_file) if raw_memories_file else str(FACTORY_DIR / "memory" / "raw_memories.jsonl"),
        "human_decisions": human_decisions or [],
    }
    
    v_output = validator_node(state, patterns)
    state.update(v_output)
    
    dod_output = dod_node(state)
    state.update(dod_output)
    
    dod_report = dod_output["dod_report"]
    v_results = state.get("validation_results", [])
    
    # Identifica o validador que causou veto
    veto_validator = None
    for r in v_results:
        if r.status != "pass":
            veto_validator = r.validator_name
            break
    if not veto_validator and not dod_report.all_passed:
        # Veto pela DoD (ex: higiene ou memória)
        for p in dod_report.pillars:
            if not p.passed:
                veto_validator = f"dod_{p.name}"
                break

    is_valid = state.get("is_valid", False)
    ready_for_human = state.get("ready_for_human_acceptance", False)
    vetoed = not (is_valid and ready_for_human)

    result_dict = {
        "case_id": case_id,
        "round": "Round_3_Independent_Oracles",
        "description": description,
        "pre_registration": {
            "hypothesis": hypothesis,
            "expected_route": expected_route,
            "failure_criterion": failure_criterion,
        },
        "mutation": {
            "verified": mutation_verified,
            "diff_hash": diff_hash,
            "diff_snippet": diff_text[:500] if diff_text else "",
        },
        "is_valid": is_valid,
        "ready_for_human_acceptance": ready_for_human,
        "vetoed": vetoed,
        "veto_validator": veto_validator,
        "validation_results": [r.dict() if hasattr(r, "dict") else str(r) for r in v_results],
        "dod_pillars": [p.dict() if hasattr(p, "dict") else str(p) for p in dod_report.pillars],
        "llm_calls": llm_calls or [],
    }

    out_file = ROUND3_DIR / f"{case_id}.json"
    out_file.write_text(json.dumps(result_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    return result_dict


def run_canaries() -> Dict[str, Any]:
    """Executa a suíte de Canários da Regra 3 (Controle Limpo + 5 Canários)."""
    print("=" * 75)
    print("🐤 Executando Bateria de Canários (Regra 3)")
    print("=" * 75)
    canary_results = {}

    # Canário 0: Controle Limpo (Entrega Verde)
    reset_worktree()
    diff_text, diff_hash = get_worktree_diff()
    res_clean = execute_pipeline(
        case_id="canary_0_clean_control",
        description="Controle Limpo (Entrega Verde de 0d1b3de)",
        hypothesis="A entrega limpa deve ser 100% aprovada sem falsos positivos.",
        expected_route="is_valid=True, ready_for_human_acceptance=True",
        failure_criterion="is_valid==False ou ready_for_human_acceptance==False (Defeito D7 / Esteira Quebrada)",
        diff_text=diff_text,
        diff_hash=diff_hash,
        mutation_verified=True,
    )
    if not res_clean["is_valid"] or not res_clean["ready_for_human_acceptance"]:
        raise CanaryFailureError(f"Defeito na Esteira: Controle Limpo foi REPROVADO! {res_clean['veto_validator']}")
    canary_results["canary_0_clean_control"] = res_clean
    print("✅ Canário 0 (Controle Limpo): PASSOU")

    # Canário 1: AST Blocker Canário
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'def analyze_preflight_plan(plan_data: dict) -> dict:',
        'def analyze_preflight_plan(plan_data: dict) -> dict:\n    eval("1+1")',
    )
    res_ast = execute_pipeline(
        case_id="canary_1_ast_eval",
        description="Canário AST: injeção de eval('1+1')",
        hypothesis="AST deve vetar imediatamente com blocker SONAR_PYTHON_S4721.",
        expected_route="veto em static_code_analysis",
        failure_criterion="static_code_analysis retorna pass",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    if res_ast["is_valid"]:
        raise CanaryFailureError("Defeito na Esteira: Canário AST não foi barrado!")
    canary_results["canary_1_ast_eval"] = res_ast
    print("✅ Canário 1 (AST Blocker): PASSOU (Barrado com sucesso)")

    # Canário 2: Pytest Fail Canário
    reset_worktree()
    target = WORKTREE_PATH / "tests" / "test_preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'def test_minimum_valid():',
        'def test_minimum_valid():\n    assert False, "canary test failure"',
    )
    res_pytest = execute_pipeline(
        case_id="canary_2_pytest_failure",
        description="Canário Pytest: injeção de assert False",
        hypothesis="Pytest deve detectar falha unitária e reprovar com fail.",
        expected_route="veto em code_quality_tests",
        failure_criterion="code_quality_tests retorna pass",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    if res_pytest["is_valid"]:
        raise CanaryFailureError("Defeito na Esteira: Canário Pytest não foi barrado!")
    canary_results["canary_2_pytest_failure"] = res_pytest
    print("✅ Canário 2 (Pytest Fail): PASSOU (Barrado com sucesso)")

    # Canário 3: Scope Drift Canário
    reset_worktree()
    target_unauth = WORKTREE_PATH / "canary_unauthorized.py"
    target_unauth.write_text("# canary drift\n", encoding="utf-8")
    diff_text, diff_hash = get_worktree_diff()
    res_scope = execute_pipeline(
        case_id="canary_3_scope_drift",
        description="Canário Scope: arquivo não autorizado na raiz",
        hypothesis="Scope validator deve acusar SCOPE_DRIFT e solicitar interrupção.",
        expected_route="requires_interrupt=True, ready_for_human=False",
        failure_criterion="ready_for_human_acceptance==True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    if res_scope["ready_for_human_acceptance"]:
        raise CanaryFailureError("Defeito na Esteira: Canário Scope não foi barrado!")
    canary_results["canary_3_scope_drift"] = res_scope
    print("✅ Canário 3 (Scope Drift): PASSOU (Barrado com sucesso)")

    # Canário 4: MCP Contract Canário
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "server.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        '    """Assess a candidate plan without observing or acting on the desktop."""',
        '    pass  # docstring removida intencionalmente para canário',
    )
    res_mcp = execute_pipeline(
        case_id="canary_4_mcp_docstring",
        description="Canário MCP: remoção de docstring da ferramenta",
        hypothesis="mcp_contract_validator deve reprovar com blocker MCP_TOOL_DOCSTRING_MISSING.",
        expected_route="veto em mcp_contract_validator",
        failure_criterion="mcp_contract_validator retorna pass",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    if res_mcp["is_valid"]:
        raise CanaryFailureError("Defeito na Esteira: Canário MCP não foi barrado!")
    canary_results["canary_4_mcp_docstring"] = res_mcp
    print("✅ Canário 4 (MCP Contract): PASSOU (Barrado com sucesso)")

    # Canário 5: DoD Hygiene Canário
    reset_worktree()
    target_tmp = WORKTREE_PATH / "canary_temp_file.tmp"
    target_tmp.write_text("temporary data", encoding="utf-8")
    diff_text, diff_hash = get_worktree_diff()
    res_hygiene = execute_pipeline(
        case_id="canary_5_dod_hygiene",
        description="Canário DoD Hygiene: arquivo .tmp residual",
        hypothesis="DoD repository_hygiene deve falhar pelo arquivo residual .tmp.",
        expected_route="dod_report.passed=False, ready_for_human=False",
        failure_criterion="ready_for_human_acceptance==True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    if not res_hygiene["vetoed"]:
        raise CanaryFailureError("Defeito na Esteira: Canário DoD Hygiene não foi barrado!")
    canary_results["canary_5_dod_hygiene"] = res_hygiene
    print("✅ Canário 5 (DoD Hygiene): PASSOU (Barrado com sucesso)")

    reset_worktree()
    (ROUND3_DIR / "canaries.json").write_text(json.dumps(canary_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("🎯 Todos os Canários foram Aprovados com Sucesso!")
    return canary_results


def run_battery_a() -> Dict[str, Any]:
    """Executa a Bateria A (10 mutações adversariais) com mutação comprovada por diff e hash."""
    print("=" * 75)
    print("🧪 Executando Bateria A — 10 Mutações Adversariais (Rodada 3)")
    print("=" * 75)
    results = {}

    # A-1: eval() em preflight.py
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'def analyze_preflight_plan(plan_data: dict) -> dict:',
        'def analyze_preflight_plan(plan_data: dict) -> dict:\n    eval("os.system(\'whoami\')")',
    )
    res_a1 = execute_pipeline(
        case_id="case_a1_eval",
        description="Injeção de eval() em preflight.py",
        hypothesis="AST deve barrar com blocker SONAR_PYTHON_S4721 por uso de função perigosa.",
        expected_route="veto em static_code_analysis",
        failure_criterion="static_code_analysis aprova ou is_valid=True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-1"] = res_a1
    print(f"A-1: vetoed={res_a1['vetoed']}, validator={res_a1['veto_validator']}")

    # A-2: Credencial hardcoded em preflight.py
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'from .plan import Plan',
        'from .plan import Plan\nAPI_KEY = "sk-proj-1234567890abcdef1234567890abcdef"',
    )
    res_a2 = execute_pipeline(
        case_id="case_a2_credential",
        description="Injeção de credencial hardcoded falsa",
        hypothesis="AST deve barrar com blocker SONAR_HARDCODED_CREDENTIALS.",
        expected_route="veto em static_code_analysis",
        failure_criterion="static_code_analysis aprova ou is_valid=True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-2"] = res_a2
    print(f"A-2: vetoed={res_a2['vetoed']}, validator={res_a2['veto_validator']}")

    # A-3: Erro de sintaxe em preflight.py
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'def analyze_preflight_plan(plan_data: dict) -> dict:',
        'def analyze_preflight_plan(plan_data: dict) -> dict:\n    def broken_syntax(:\n        pass',
    )
    res_a3 = execute_pipeline(
        case_id="case_a3_syntax",
        description="Erro de sintaxe em preflight.py",
        hypothesis="Sintaxe inválida impede compilação do AST e execução dos testes.",
        expected_route="veto em static_code_analysis e code_quality_tests",
        failure_criterion="is_valid=True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-3"] = res_a3
    print(f"A-3: vetoed={res_a3['vetoed']}, validator={res_a3['veto_validator']}")

    # A-4: Teste unitário que falha (Correção do replace da rodada 2)
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'result["status"] = "valid"',
        'result["status"] = "invalid_status"',
    )
    res_a4 = execute_pipeline(
        case_id="case_a4_test_failure",
        description="Falha de teste unitário comprovada por mutação real",
        hypothesis="Pytest falha em test_minimum_valid e é barrado por code_quality_tests.",
        expected_route="veto em code_quality_tests",
        failure_criterion="code_quality_tests retorna pass",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-4"] = res_a4
    print(f"A-4: vetoed={res_a4['vetoed']}, validator={res_a4['veto_validator']}")

    # A-5: Scope drift
    reset_worktree()
    scripts_dir = WORKTREE_PATH / "scripts"
    scripts_dir.mkdir(exist_ok=True, parents=True)
    (scripts_dir / "unauthorized.py").write_text("# out of scope\n", encoding="utf-8")
    diff_text, diff_hash = get_worktree_diff()
    res_a5 = execute_pipeline(
        case_id="case_a5_scope_drift",
        description="Desvio de escopo fora da whitelist",
        hypothesis="scope_validator sinaliza requires_interrupt e DoD não atinge ready_for_human.",
        expected_route="ready_for_human_acceptance=False por parada HITL não aprovada",
        failure_criterion="ready_for_human_acceptance=True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-5"] = res_a5
    print(f"A-5: vetoed={res_a5['vetoed']}, validator={res_a5['veto_validator']}")

    # A-6: Arquivo .tmp residual
    reset_worktree()
    (WORKTREE_PATH / "debug_dump.tmp").write_text("temp junk", encoding="utf-8")
    diff_text, diff_hash = get_worktree_diff()
    res_a6 = execute_pipeline(
        case_id="case_a6_junk_tmp",
        description="Arquivo .tmp residual no repositório",
        hypothesis="DoD repository_hygiene detecta arquivo temporário espúrio e veta.",
        expected_route="ready_for_human_acceptance=False, veto em dod_repository_hygiene",
        failure_criterion="ready_for_human_acceptance=True",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-6"] = res_a6
    print(f"A-6: vetoed={res_a6['vetoed']}, validator={res_a6['veto_validator']}")

    # A-7: Tool sem docstring
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "server.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        '    """Assess a candidate plan without observing or acting on the desktop."""',
        '    pass  # docstring ausente',
    )
    res_a7 = execute_pipeline(
        case_id="case_a7_empty_docstring",
        description="Tool MCP sem docstring",
        hypothesis="mcp_contract_validator deve barrar com blocker MCP_TOOL_DOCSTRING_MISSING.",
        expected_route="veto em mcp_contract_validator",
        failure_criterion="mcp_contract_validator retorna pass",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-7"] = res_a7
    print(f"A-7: vetoed={res_a7['vetoed']}, validator={res_a7['veto_validator']}")

    # A-8: WAL vazio com 0 bytes
    reset_worktree()
    empty_wal = FACTORY_DIR / "memory" / "empty_test_wal.jsonl"
    empty_wal.write_text("", encoding="utf-8")
    diff_text, diff_hash = get_worktree_diff()
    res_a8 = execute_pipeline(
        case_id="case_a8_empty_wal",
        description="WAL vazio com 0 bytes",
        hypothesis="session_memory_recorded na DoD reprova por 0 bytes no WAL.",
        expected_route="ready_for_human_acceptance=False, veto em dod_session_memory_recorded",
        failure_criterion="ready_for_human_acceptance=True",
        raw_memories_file=empty_wal,
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    empty_wal.unlink(missing_ok=True)
    results["A-8"] = res_a8
    print(f"A-8: vetoed={res_a8['vetoed']}, validator={res_a8['veto_validator']}")

    # A-9: Lacuna conhecida de oráculo (reachability por on_failure)
    reset_worktree()
    target = WORKTREE_PATH / "laya_computer" / "preflight.py"
    old_reach = (
        '        reachable = set()\n'
        '        by_id = {step.id: step for step in plan.steps}\n'
        '        current = plan.first_step_id\n'
        '        while current is not None and current not in reachable:\n'
        '            reachable.add(current)\n'
        '            current = by_id[current].next_step'
    )
    new_reach = (
        '        reachable = set()\n'
        '        by_id = {step.id: step for step in plan.steps}\n'
        '        queue = [plan.first_step_id] if plan.first_step_id else []\n'
        '        while queue:\n'
        '            curr_id = queue.pop(0)\n'
        '            if curr_id in reachable or curr_id not in by_id:\n'
        '                continue\n'
        '            reachable.add(curr_id)\n'
        '            step = by_id[curr_id]\n'
        '            if step.next_step:\n'
        '                queue.append(step.next_step)\n'
        '            if getattr(step, "on_failure", None):\n'
        '                queue.append(step.on_failure)'
    )
    diff_text, diff_hash = verify_mutation_applied(target, old_reach, new_reach)
    res_a9 = execute_pipeline(
        case_id="case_a9_blind_oracle",
        description="Lacuna conhecida de oráculo: reachability expandido para on_failure",
        hypothesis="A suíte atual não testa caminho negativo de on_failure, logo a esteira antiga APROVA (lacuna).",
        expected_route="is_valid=True, ready_for_human_acceptance=True (lacuna confirmada a ser coberta no Passo 2)",
        failure_criterion="veto prematuro sem oráculo de aceitação",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-9"] = res_a9
    print(f"A-9: vetoed={res_a9['vetoed']}, is_valid={res_a9['is_valid']} (Lacuna confirmada: {not res_a9['vetoed']})")

    # A-10: Teste desativado com @pytest.mark.skip (D6 corrigido e mutação válida)
    reset_worktree()
    target = WORKTREE_PATH / "tests" / "test_preflight.py"
    diff_text, diff_hash = verify_mutation_applied(
        target,
        'def test_minimum_valid():',
        'import pytest\n\n@pytest.mark.skip(reason="bypass test")\ndef test_minimum_valid():',
    )
    res_a10 = execute_pipeline(
        case_id="case_a10_test_tampering",
        description="Teste desativado com @pytest.mark.skip dentro de função",
        hypothesis="code_quality_tests detecta 'skipped' no stdout do pytest e veta com TEST_TAMPERING_DETECTED.",
        expected_route="veto em code_quality_tests",
        failure_criterion="code_quality_tests retorna pass",
        diff_text=diff_text,
        diff_hash=diff_hash,
    )
    results["A-10"] = res_a10
    print(f"A-10: vetoed={res_a10['vetoed']}, validator={res_a10['veto_validator']}")

    reset_worktree()
    (ROUND3_DIR / "battery_a_summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n🎯 Bateria A Concluída!")
    return results


if __name__ == "__main__":
    run_canaries()
    run_battery_a()

