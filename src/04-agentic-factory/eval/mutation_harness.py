"""Harness de Teste de Mutação (O4) com Linha de Base, Limiar e Feedback ao Worker.

Fluxo:
1. Gera mutantes sintéticos focados estritamente nas linhas alteradas da feature `preflight.py`.
2. Executa a suíte de testes existente (tests/test_preflight.py) para medir o baseline_score sem limiar.
3. Propõe formalmente um limiar mínimo com justificativa técnica.
4. Passa os mutantes sobreviventes ao Worker (gpt-6-luna) como feedback (linha e diff).
5. O worker escreve testes unitários cirúrgicos para eliminar os sobreviventes.
6. Mede o escore final de mutação pós-ciclo de reparo e o custo em novos testes e tokens.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

WORKTREE_PATH = Path("/Users/matheusborges/github/mcps-catalog-worktree-exp04/laya-computer").resolve()
ROUND3_DIR = FACTORY_DIR / "eval" / "round3"
ROUND3_DIR.mkdir(parents=True, exist_ok=True)

from eval.canary_harness import reset_worktree, get_worktree_diff
from agents.llm_client import invoke_worker_codex


@dataclass
class Mutant:
    mutant_id: str
    line_number: int
    description: str
    original_code: str
    mutated_code: str
    status: str = "pending"  # killed, survived, error
    failing_test: str = ""


# Catálogo formal de mutantes cirúrgicos nas linhas de preflight.py (linhas 33 a 65)
MUTANTS_CATALOG = [
    Mutant(
        mutant_id="MUT_01",
        line_number=33,
        description="Altera inicialização de status de 'valid' para 'invalid'",
        original_code='result["status"] = "valid"',
        mutated_code='result["status"] = "invalid"',
    ),
    Mutant(
        mutant_id="MUT_02",
        line_number=37,
        description="Troca operador booleano 'and' por 'or' no loop de reachability",
        original_code='while current is not None and current not in reachable:',
        mutated_code='while current is not None or current not in reachable:',
    ),
    Mutant(
        mutant_id="MUT_03",
        line_number=43,
        description="Troca 'any' por 'all' na detecção de nós inalcançáveis",
        original_code='if any(s.id not in reachable for s in plan.steps):',
        mutated_code='if all(s.id not in reachable for s in plan.steps):',
    ),
    Mutant(
        mutant_id="MUT_04",
        line_number=44,
        description="Omite invalidação de status quando há nó inalcançável",
        original_code='            result["status"] = "invalid"',
        mutated_code='            pass  # omitido',
    ),
    Mutant(
        mutant_id="MUT_05",
        line_number=45,
        description="Omite recomendação 'repair' quando há nó inalcançável",
        original_code='            result["recommendation"] = "repair"',
        mutated_code='            pass  # omitido',
    ),
    Mutant(
        mutant_id="MUT_06",
        line_number=49,
        description="Inverte checagem de action set_value (== vira !=)",
        original_code='            if step.action.value == "set_value":',
        mutated_code='            if step.action.value != "set_value":',
    ),
    Mutant(
        mutant_id="MUT_07",
        line_number=50,
        description="Omite registro de risco writes_user_data",
        original_code='                risks.add("writes_user_data")',
        mutated_code='                pass  # omitido',
    ),
    Mutant(
        mutant_id="MUT_08",
        line_number=54,
        description="Afrouxa checagem de teclas perigosas de OR para AND",
        original_code='            if key in dangerous or "command" in key or "terminal" in key:',
        mutated_code='            if key in dangerous and "command" in key and "terminal" in key:',
    ),
    Mutant(
        mutant_id="MUT_09",
        line_number=55,
        description="Omite registro de risco destructive_keys",
        original_code='                risks.add("destructive_keys")',
        mutated_code='                pass  # omitido',
    ),
    Mutant(
        mutant_id="MUT_10",
        line_number=57,
        description="Inverte checagem de allow_partial_observation (nega flag)",
        original_code='            if step.allow_partial_observation:',
        mutated_code='            if not step.allow_partial_observation:',
    ),
    Mutant(
        mutant_id="MUT_11",
        line_number=58,
        description="Omite registro de risco partial_observation",
        original_code='                risks.add("partial_observation")',
        mutated_code='                pass  # omitido',
    ),
    Mutant(
        mutant_id="MUT_12",
        line_number=61,
        description="Afrouxa regra de recomendação de risco de OR para AND",
        original_code='        if "partial_observation" in risks or "destructive_keys" in risks or "writes_user_data" in risks:',
        mutated_code='        if "partial_observation" in risks and "destructive_keys" in risks and "writes_user_data" in risks:',
    ),
    Mutant(
        mutant_id="MUT_13",
        line_number=64,
        description="Altera recomendação de plano limpo de 'proceed_to_inspection' para 'repair'",
        original_code='            result["recommendation"] = "proceed_to_inspection"',
        mutated_code='            result["recommendation"] = "repair"',
    ),
]


def test_single_mutant(mutant: Mutant, test_file_subpath: str = "tests/test_preflight.py") -> Mutant:
    """Aplica uma mutação no worktree, roda a suíte de testes e classifica em killed ou survived."""
    reset_worktree()
    target_file = WORKTREE_PATH / "laya_computer" / "preflight.py"
    content = target_file.read_text(encoding="utf-8")

    if mutant.original_code not in content:
        mutant.status = "error"
        mutant.failing_test = f"String original não encontrada: {mutant.original_code}"
        return mutant

    mutated_content = content.replace(mutant.original_code, mutant.mutated_code, 1)
    target_file.write_text(mutated_content, encoding="utf-8")

    # Executa pytest
    proc = subprocess.run(
        [str(WORKTREE_PATH / ".venv" / "bin" / "pytest"), "-q", test_file_subpath],
        cwd=str(WORKTREE_PATH),
        capture_output=True,
        text=True,
        timeout=30,
    )

    if proc.returncode != 0:
        mutant.status = "killed"
        lines = [l for l in proc.stdout.splitlines() if "FAILED" in l or "ERROR" in l]
        mutant.failing_test = lines[0].strip() if lines else "pytest_exit_nonzero"
    else:
        mutant.status = "survived"
        mutant.failing_test = ""

    reset_worktree()
    return mutant


def evaluate_mutation_score(mutants: List[Mutant], test_file_subpath: str = "tests/test_preflight.py") -> Tuple[float, List[Mutant]]:
    """Avalia o conjunto de mutantes contra a suíte informada."""
    evaluated = []
    killed_count = 0

    for m in mutants:
        m_copy = copy.deepcopy(m)
        res = test_single_mutant(m_copy, test_file_subpath=test_file_subpath)
        evaluated.append(res)
        if res.status == "killed":
            killed_count += 1

    score = round((killed_count / len(evaluated)) * 100, 1) if evaluated else 0.0
    return score, evaluated


def run_mutation_experiment() -> Dict[str, Any]:
    """Executa a medição de baseline, ciclo de feedback ao worker e pós-reforço."""
    print("=" * 75)
    print("🧬 Executando Testes de Mutação (O4) — Linhas Alteradas")
    print("=" * 75)

    # 1. Medição de Linha de Base (sem limiar)
    print("\n▶ 1. Medindo Escore de Mutação da Linha de Base (Suíte Atual)...")
    baseline_score, evaluated_baseline = evaluate_mutation_score(MUTANTS_CATALOG, "tests/test_preflight.py")
    
    survived_mutants = [m for m in evaluated_baseline if m.status == "survived"]
    killed_mutants = [m for m in evaluated_baseline if m.status == "killed"]

    print(f"  Baseline: {len(killed_mutants)}/{len(evaluated_baseline)} mortos ({baseline_score}% score)")
    print(f"  Mutantes sobreviventes: {len(survived_mutants)}")
    for sm in survived_mutants:
        print(f"   - [{sm.mutant_id}] Linha {sm.line_number}: {sm.description}")

    # 2. Proposição Formal do Limiar
    # Justificativa técnica:
    # A suíte inicial já cobre casos básicos, mas deixa brechas em combinações booleanas parciais de risco
    # (ex: regra 08 onde teclas perigosas com OR foram afrouxadas para AND e a regra 12 de recomendação combinada).
    # O limiar de qualidade de mutação para código de infraestrutura de controle desktop deve ser >= 85.0%,
    # garantindo que nenhuma cláusula de proteção de risco passe desapercebida.
    proposed_threshold = 85.0
    threshold_justification = (
        "O código de avaliação estática (preflight) atua como barreira primária contra execuções destrutivas no SO. "
        "Um escore de mutação inferior a 85% permite mutantes em regras booleanas de risco (como troca de OR por AND em teclas "
        "destrutivas) passarem indetectados. Propõe-se o limiar mínimo de 85.0% nas linhas alteradas."
    )

    # 3. Feedback Cirúrgico ao Worker (gpt-6-luna)
    survivors_feedback = []
    for sm in survived_mutants:
        survivors_feedback.append({
            "mutant_id": sm.mutant_id,
            "line_number": sm.line_number,
            "description": sm.description,
            "diff": f"- {sm.original_code}\n+ {sm.mutated_code}",
        })

    worker_prompt = f"""You are the software factory worker. We performed mutation testing on `laya_computer/preflight.py` and found {len(survived_mutants)} SURVIVING mutants that were NOT killed by `tests/test_preflight.py`.

Surviving Mutants:
{json.dumps(survivors_feedback, indent=2)}

Task:
Write NEW unit tests in pytest format that specifically KILL these surviving mutants.
Your tests must be added to a new test file: `tests/test_preflight_mutants.py`.
Output ONLY the Python code for `tests/test_preflight_mutants.py` enclosed in ```python ... ``` without markdown conversation.
Ensure all your tests import `analyze_preflight_plan` and `plan` correctly and pass on the UNMUTATED code!
"""
    system_prompt = "You are a test-driven specialist in mutation testing. Write precise assertions to eliminate surviving mutants."

    print("\n▶ 2. Enviando mutantes sobreviventes como feedback para o worker gpt-6-luna...")
    llm_call = invoke_worker_codex(worker_prompt, system=system_prompt)
    print(f"  Worker respondeu ({llm_call.total_tokens} tokens em {llm_call.latency_ms}ms)")

    # Extrai o código Python gerado pelo worker
    raw_code = llm_call.content
    code_match = raw_code
    if "```python" in raw_code:
        code_match = raw_code.split("```python")[1].split("```")[0].strip()
    elif "```" in raw_code:
        code_match = raw_code.split("```")[1].split("```")[0].strip()

    # Grava o arquivo de reforço de testes no worktree
    reinforcement_test_file = WORKTREE_PATH / "tests" / "test_preflight_mutants.py"
    reinforcement_test_file.write_text(code_match, encoding="utf-8")
    print(f"  Testes de reforço gravados em: {reinforcement_test_file.name}")

    # Confere se os novos testes passam no código não-mutado
    p_check = subprocess.run(
        [str(WORKTREE_PATH / ".venv" / "bin" / "pytest"), "-q", str(reinforcement_test_file)],
        cwd=str(WORKTREE_PATH),
        capture_output=True,
        text=True,
    )
    print(f"  Execução dos novos testes no código limpo: returncode={p_check.returncode}")
    if p_check.returncode != 0:
        print(f"  AVISO: Alguns testes falharam no código limpo:\n{p_check.stdout[:400]}")

    # 4. Re-avaliação pós-ciclo de feedback
    print("\n▶ 3. Re-avaliando Escore de Mutação com a Suíte Reforçada...")
    post_score, evaluated_post = evaluate_mutation_score(MUTANTS_CATALOG, "tests")

    post_killed = [m for m in evaluated_post if m.status == "killed"]
    post_survived = [m for m in evaluated_post if m.status == "survived"]

    print(f"  Escore Pós-Reforço: {len(post_killed)}/{len(evaluated_post)} mortos ({post_score}% score)")
    print(f"  Delta de Escore: +{round(post_score - baseline_score, 1)}%")

    # Conta quantos testes foram adicionados
    import ast
    try:
        t_tree = ast.parse(code_match)
        new_test_count = sum(1 for n in ast.walk(t_tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"))
    except Exception:
        new_test_count = 1

    result_data = {
        "round": "Round_3_Mutation_O4",
        "feature": "preflight_plan",
        "target_file": "laya_computer/preflight.py",
        "lines_evaluated": "33-65",
        "baseline": {
            "total_mutants": len(MUTANTS_CATALOG),
            "killed_count": len(killed_mutants),
            "survived_count": len(survived_mutants),
            "mutation_score": baseline_score,
            "survivors": [asdict(sm) for sm in survived_mutants],
        },
        "proposed_threshold": {
            "threshold_percent": proposed_threshold,
            "justification": threshold_justification,
            "baseline_met_threshold": baseline_score >= proposed_threshold,
        },
        "worker_feedback_cycle": {
            "model": llm_call.model,
            "route": llm_call.route,
            "tokens": {
                "prompt_tokens": llm_call.prompt_tokens,
                "completion_tokens": llm_call.completion_tokens,
                "total_tokens": llm_call.total_tokens,
            },
            "latency_ms": llm_call.latency_ms,
            "new_tests_added_count": new_test_count,
            "reinforcement_file": "tests/test_preflight_mutants.py",
        },
        "post_feedback": {
            "total_mutants": len(MUTANTS_CATALOG),
            "killed_count": len(post_killed),
            "survived_count": len(post_survived),
            "mutation_score": post_score,
            "score_delta": round(post_score - baseline_score, 1),
            "threshold_achieved": post_score >= proposed_threshold,
            "survivors": [asdict(sm) for sm in post_survived],
        },
    }

    reset_worktree()
    (ROUND3_DIR / "mutation_testing_results.json").write_text(
        json.dumps(result_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print("\n🎯 Experimento de Mutação Concluído com Sucesso!")
    return result_data


if __name__ == "__main__":
    run_mutation_experiment()
