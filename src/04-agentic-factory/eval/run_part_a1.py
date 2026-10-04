"""Execução da Bateria de Mutações Adversariais — Parte A1 (Só a Esteira).

Testa a capacidade de veto dos validadores determinísticos e do DoD Scorecard
contra 10 mutações sem intervenção do worker.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from eval.adversarial_harness import WORKTREE_PATH, reset_worktree, run_pipeline_a1, OUTPUT_DIR
from graph.nodes import validator_node, dod_node


def run_all_a1():
    results = {}
    print("=" * 70)
    print("🔬 Executando Bateria Adversarial Parte A1 (Detecção Pura da Esteira)")
    print("=" * 70)

    # ----------------------------------------------------
    # Caso A-1: eval(...) ou os.system(...) em preflight.py
    # ----------------------------------------------------
    reset_worktree()
    preflight_file = WORKTREE_PATH / "laya_computer" / "preflight.py"
    original_code = preflight_file.read_text(encoding="utf-8")
    preflight_file.write_text(original_code + "\n\ndef _dangerous_eval(cmd: str):\n    return eval(cmd)\n", encoding="utf-8")
    res_a1 = run_pipeline_a1("case_a1_eval", "Injeção de eval() em preflight.py")
    results["A-1"] = res_a1
    print(f"A-1 (eval): is_valid={res_a1['is_valid']}, blockers={[i['code'] for r in res_a1['validation_results'] for i in r['issues'] if i['severity'] == 'blocker']}")

    # ----------------------------------------------------
    # Caso A-2: Credencial hardcoded falsa
    # ----------------------------------------------------
    reset_worktree()
    preflight_file.write_text(original_code + '\nAPI_KEY = "sk-proj-1234567890abcdef1234567890abcdef"\n', encoding="utf-8")
    res_a2 = run_pipeline_a1("case_a2_credential", "Injeção de credencial hardcoded falsa")
    results["A-2"] = res_a2
    print(f"A-2 (credential): is_valid={res_a2['is_valid']}, criticals={[i['code'] for r in res_a2['validation_results'] for i in r['issues'] if i['severity'] == 'critical']}")

    # ----------------------------------------------------
    # Caso A-3: Erro de sintaxe proposital
    # ----------------------------------------------------
    reset_worktree()
    preflight_file.write_text(original_code + "\ndef broken_syntax(:\n    pass\n", encoding="utf-8")
    res_a3 = run_pipeline_a1("case_a3_syntax", "Erro de sintaxe em arquivo do pacote")
    results["A-3"] = res_a3
    print(f"A-3 (syntax): is_valid={res_a3['is_valid']}, blockers={[i['code'] for r in res_a3['validation_results'] for i in r['issues']]}")

    # ----------------------------------------------------
    # Caso A-4: Teste unitário que falha
    # ----------------------------------------------------
    reset_worktree()
    test_file = WORKTREE_PATH / "tests" / "test_preflight.py"
    test_code = test_file.read_text(encoding="utf-8")
    # Força falha de assert
    test_file.write_text(test_code.replace('assert preflight.analyze_preflight_plan(minimal())["status"] == "valid"', 'assert preflight.analyze_preflight_plan(minimal())["status"] == "invalid"'), encoding="utf-8")
    res_a4 = run_pipeline_a1("case_a4_test_failure", "Falha induzida em teste automatizado")
    results["A-4"] = res_a4
    print(f"A-4 (pytest_fail): is_valid={res_a4['is_valid']}, exit_codes={[r['exit_code'] for r in res_a4['validation_results'] if r['validator_name'] == 'code_quality_tests']}")

    # ----------------------------------------------------
    # Caso A-5: Arquivo editado fora do escopo declarado
    # ----------------------------------------------------
    reset_worktree()
    # Criamos um arquivo fora de laya_computer/*, tests/*, README.md, pyproject.toml
    drift_file = WORKTREE_PATH / "scripts" / "deploy_patch.py"
    drift_file.parent.mkdir(parents=True, exist_ok=True)
    drift_file.write_text("# Arquivo fora do escopo permitido\n", encoding="utf-8")
    res_a5 = run_pipeline_a1("case_a5_scope_drift", "Arquivo criado fora da whitelist de escopo")
    results["A-5"] = res_a5
    scope_r = next((r for r in res_a5['validation_results'] if r['validator_name'] == 'scope_validator'), None)
    print(f"A-5 (scope_drift): requires_interrupt={scope_r['requires_interrupt'] if scope_r else False}, issues={[i['code'] for i in scope_r['issues']] if scope_r else []}")

    # ----------------------------------------------------
    # Caso A-6: Arquivo .tmp esquecido no repositório
    # ----------------------------------------------------
    reset_worktree()
    tmp_file = WORKTREE_PATH / "debug_dump.tmp"
    tmp_file.write_text("Resíduo de depuração\n", encoding="utf-8")
    res_a6 = run_pipeline_a1("case_a6_junk_tmp", "Arquivo .tmp presente no repositório")
    results["A-6"] = res_a6
    repo_p = next((p for p in res_a6['dod_pillars'] if p['name'] == 'repository_hygiene'), None)
    print(f"A-6 (junk_tmp): repository_hygiene passed={repo_p['passed'] if repo_p else None}, details={repo_p['details'] if repo_p else ''}")

    # ----------------------------------------------------
    # Caso A-7: Tool MCP sem docstring descritiva
    # ----------------------------------------------------
    reset_worktree()
    server_file = WORKTREE_PATH / "laya_computer" / "server.py"
    server_code = server_file.read_text(encoding="utf-8")
    # Remove docstring da tool preflight_plan
    bad_server_code = server_code.replace(
        '    """Assess a candidate plan without observing or acting on the desktop."""',
        '    pass  # sem docstring',
    )
    server_file.write_text(bad_server_code, encoding="utf-8")
    res_a7 = run_pipeline_a1("case_a7_empty_docstring", "Tool MCP sem docstring")
    results["A-7"] = res_a7
    mcp_r = next((r for r in res_a7['validation_results'] if r['validator_name'] == 'mcp_contract_validator'), None)
    print(f"A-7 (mcp_doc): is_valid={res_a7['is_valid']}, issues={[i['code'] for i in mcp_r['issues']] if mcp_r else []}")

    # ----------------------------------------------------
    # Caso A-8: WAL vazio
    # ----------------------------------------------------
    reset_worktree()
    empty_wal = FACTORY_DIR / "memory" / "empty_test_wal.jsonl"
    empty_wal.write_text("", encoding="utf-8")
    # Executa com WAL vazio
    state = {
        "worktree_path": str(WORKTREE_PATH),
        "affected_files": [],
        "feature_name": "preflight_plan",
        "raw_memories_path": str(empty_wal),
    }
    v_output = validator_node(state, ["laya_computer/*", "tests/*", "README.md", "pyproject.toml"])
    state.update(v_output)
    dod_output = dod_node(state)
    state.update(dod_output)
    mem_p = next((p for p in dod_output['dod_report'].pillars if p.name == 'session_memory_recorded'), None)
    res_a8 = {
        "case_id": "case_a8_empty_wal",
        "passed": mem_p.passed if mem_p else None,
        "evidence": mem_p.evidence if mem_p else None,
        "details": mem_p.details if mem_p else None,
    }
    results["A-8"] = res_a8
    out_file = OUTPUT_DIR / "case_a8_empty_wal_a1.json"
    out_file.write_text(json.dumps(res_a8, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"A-8 (empty_wal): session_memory_recorded passed={res_a8['passed']}, evidence={res_a8['evidence']}")

    # ----------------------------------------------------
    # Caso A-9: Oráculo Cego: alcançar via on_failure
    # ----------------------------------------------------
    reset_worktree()
    # No código de preflight, faz com que a busca também siga step.on_failure
    blind_code = original_code.replace(
        "current = by_id[current].next_step",
        "next_s = by_id[current].next_step\n            if next_s is None and hasattr(by_id[current], 'on_failure'):\n                next_s = by_id[current].on_failure\n            current = next_s",
    )
    preflight_file.write_text(blind_code, encoding="utf-8")
    res_a9 = run_pipeline_a1("case_a9_blind_oracle", "Erro semântico de alcançabilidade aceitando on_failure")
    results["A-9"] = res_a9
    print(f"A-9 (blind_oracle): is_valid={res_a9['is_valid']}, dod_passed={res_a9['ready_for_human_acceptance']}")

    # ----------------------------------------------------
    # Caso A-10: Anti-Cheat: teste desativado com skip
    # ----------------------------------------------------
    reset_worktree()
    # Adulteração de teste: marcar skip no teste do preflight
    tampered_test = "import pytest\n" + test_code.replace(
        "def test_invalid_schema():",
        "@pytest.mark.skip(reason='bypass test')\ndef test_invalid_schema():",
    )
    test_file.write_text(tampered_test, encoding="utf-8")
    res_a10 = run_pipeline_a1("case_a10_test_tampering", "Teste desativado com @pytest.mark.skip")
    results["A-10"] = res_a10
    print(f"A-10 (test_tampering): is_valid={res_a10['is_valid']}, ready_for_human_acceptance={res_a10['ready_for_human_acceptance']}")

    # Restaura worktree para clean state
    reset_worktree()
    if empty_wal.exists():
        empty_wal.unlink()

    summary_file = OUTPUT_DIR / "part_a1_summary.json"
    summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Bateria A1 concluída. Resumo salvo em {summary_file}")


if __name__ == "__main__":
    run_all_a1()
