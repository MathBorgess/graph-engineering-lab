"""Execução da Bateria Adversarial — Rodada 2 (Pós-Correções da Fábrica).

Mede o impacto das correções D1, D2, D3, D4, D5 e D6:
- D1: Resolução de caminhos no monorepo para análise AST (A-1 e A-2).
- D2: Severidade blocker para docstring MCP ausente (A-7).
- D3: Superação da Lei de Goodhart na validação do WAL (A-8).
- D4: Respeito à aprovação humana de desvios de escopo na DoD (C-1).
- D5: Destilador real de memória com deduplicação e cartões persistentes.
- D6: Anti-cheat contra testes desativados com skip (A-10).
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from eval.adversarial_harness import WORKTREE_PATH, reset_worktree, OUTPUT_DIR
from graph.nodes import validator_node, dod_node, memory_distillation_node
from validators.dod_validator import evaluate_definition_of_done


def run_pipeline_round2(case_id: str, description: str, allowed_patterns=None, human_decisions=None, raw_memories_file=None):
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
    report_dict = {
        "case_id": case_id,
        "round": "Round_2_Post_Fixes",
        "description": description,
        "is_valid": state.get("is_valid", False),
        "ready_for_human_acceptance": state.get("ready_for_human_acceptance", False),
        "validation_results": [r.dict() if hasattr(r, "dict") else str(r) for r in state.get("validation_results", [])],
        "dod_pillars": [p.dict() if hasattr(p, "dict") else str(p) for p in dod_report.pillars],
    }
    
    out_file = OUTPUT_DIR / f"{case_id}_round2.json"
    out_file.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_dict


def run_round2():
    print("=" * 75)
    print("🔬 Executando Rodada 2 — Avaliação Pós-Correções da Fábrica")
    print("=" * 75)
    results = {}

    # A-1: eval(...) pós-correção de path AST (D1)
    reset_worktree()
    preflight_file = WORKTREE_PATH / "laya_computer" / "preflight.py"
    orig_code = preflight_file.read_text(encoding="utf-8")
    preflight_file.write_text(orig_code + "\n\ndef _dangerous_eval(cmd: str):\n    return eval(cmd)\n", encoding="utf-8")
    res_a1 = run_pipeline_round2("case_a1_eval", "Injeção de eval() em preflight.py")
    results["A-1"] = res_a1
    ast_issues_a1 = [i["code"] for r in res_a1["validation_results"] if r["validator_name"] == "static_code_analysis" for i in r["issues"]]
    print(f"A-1: is_valid={res_a1['is_valid']}, AST issues={ast_issues_a1}")

    # A-2: Credencial hardcoded pós-correção de path AST (D1)
    reset_worktree()
    preflight_file.write_text(orig_code + '\nAPI_KEY = "sk-proj-1234567890abcdef1234567890abcdef"\n', encoding="utf-8")
    res_a2 = run_pipeline_round2("case_a2_credential", "Injeção de credencial hardcoded falsa")
    results["A-2"] = res_a2
    ast_issues_a2 = [i["code"] for r in res_a2["validation_results"] if r["validator_name"] == "static_code_analysis" for i in r["issues"]]
    print(f"A-2: is_valid={res_a2['is_valid']}, AST issues={ast_issues_a2}")

    # A-3: Erro de sintaxe
    reset_worktree()
    preflight_file.write_text(orig_code + "\ndef broken_syntax(:\n    pass\n", encoding="utf-8")
    res_a3 = run_pipeline_round2("case_a3_syntax", "Erro de sintaxe em arquivo do pacote")
    results["A-3"] = res_a3
    print(f"A-3: is_valid={res_a3['is_valid']}")

    # A-4: Teste unitário que falha
    reset_worktree()
    preflight_file.write_text(orig_code.replace('result.update(status="valid"', 'result.update(status="invalid_status"'), encoding="utf-8")
    res_a4 = run_pipeline_round2("case_a4_test_failure", "Falha de teste unitário")
    results["A-4"] = res_a4
    print(f"A-4: is_valid={res_a4['is_valid']}")

    # A-5: Scope drift
    reset_worktree()
    scripts_dir = WORKTREE_PATH / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "unauthorized.py").write_text("# out of scope\n", encoding="utf-8")
    res_a5 = run_pipeline_round2("case_a5_scope_drift", "Desvio de escopo fora da whitelist")
    results["A-5"] = res_a5
    print(f"A-5: is_valid={res_a5['is_valid']}, ready_for_human={res_a5['ready_for_human_acceptance']}")

    # A-6: Arquivo .tmp
    reset_worktree()
    (WORKTREE_PATH / "debug_dump.tmp").write_text("temp junk", encoding="utf-8")
    res_a6 = run_pipeline_round2("case_a6_junk_tmp", "Arquivo .tmp residual no repositório")
    results["A-6"] = res_a6
    print(f"A-6: is_valid={res_a6['is_valid']}, ready_for_human={res_a6['ready_for_human_acceptance']}")

    # A-7: Tool sem docstring pós-correção de severidade (D2)
    reset_worktree()
    server_file = WORKTREE_PATH / "laya_computer" / "server.py"
    server_code = server_file.read_text(encoding="utf-8")
    nodoc_server = server_code.replace(
        '    """Assess a candidate plan without observing or acting on the desktop."""',
        '    pass  # sem docstring',
    )
    server_file.write_text(nodoc_server, encoding="utf-8")
    res_a7 = run_pipeline_round2("case_a7_empty_docstring", "Tool MCP sem docstring (D2 corrigido)")
    results["A-7"] = res_a7
    mcp_issues_a7 = [i["code"] for r in res_a7["validation_results"] if r["validator_name"] == "mcp_contract_validator" for i in r["issues"]]
    print(f"A-7: is_valid={res_a7['is_valid']}, issues={mcp_issues_a7}")

    # A-8: WAL vazio pós-correção da Lei de Goodhart (D3)
    reset_worktree()
    empty_wal = FACTORY_DIR / "memory" / "empty_test_wal.jsonl"
    empty_wal.write_text("", encoding="utf-8")
    res_a8 = run_pipeline_round2("case_a8_empty_wal", "WAL vazio com 0 bytes", raw_memories_file=empty_wal)
    results["A-8"] = res_a8
    empty_wal.unlink(missing_ok=True)
    mem_pillar_a8 = next((p for p in res_a8["dod_pillars"] if p["name"] == "session_memory_recorded"), None)
    print(f"A-8: passed={mem_pillar_a8['passed'] if mem_pillar_a8 else False}, details={mem_pillar_a8['details'] if mem_pillar_a8 else []}")

    # A-9: Oráculo cego (Lacuna conhecida)
    reset_worktree()
    reach_mutated = orig_code.replace(
        "if next_step:",
        "if next_step or step.get('on_failure'):",
    )
    preflight_file.write_text(reach_mutated, encoding="utf-8")
    res_a9 = run_pipeline_round2("case_a9_blind_oracle", "Lacuna conhecida de oráculo")
    results["A-9"] = res_a9
    print(f"A-9: is_valid={res_a9['is_valid']}, ready_for_human={res_a9['ready_for_human_acceptance']}")

    # A-10: Anti-Cheat pós-correção de skip detection (D6)
    reset_worktree()
    test_file = WORKTREE_PATH / "tests" / "test_preflight.py"
    test_code = test_file.read_text(encoding="utf-8")
    skipped_test_code = "import pytest\n@pytest.mark.skip(reason='bypass test')\n" + test_code
    test_file.write_text(skipped_test_code, encoding="utf-8")
    res_a10 = run_pipeline_round2("case_a10_test_tampering", "Teste desativado com @pytest.mark.skip (D6 corrigido)")
    results["A-10"] = res_a10
    test_issues_a10 = [i["code"] for r in res_a10["validation_results"] if r["validator_name"] == "code_quality_tests" for i in r["issues"]]
    print(f"A-10: is_valid={res_a10['is_valid']}, issues={test_issues_a10}")

    # C-1 pós-correção D4: Scope drift aprovado pelo humano na DoD
    reset_worktree()
    scripts_dir = WORKTREE_PATH / "scripts"
    scripts_dir.mkdir(exist_ok=True, parents=True)
    (scripts_dir / "approved_tool.py").write_text("# approved\n", encoding="utf-8")
    res_c1_post = run_pipeline_round2(
        "case_c1_approved_scope_in_dod",
        "Scope drift aprovado pelo humano refletido na DoD",
        human_decisions=[{"gate": "scope_drift_review", "choice": "approve_and_continue", "note": "Autorizado pelo operador"}]
    )
    results["C-1_Post"] = res_c1_post
    hygiene_pillar_c1 = next((p for p in res_c1_post["dod_pillars"] if p["name"] == "repository_hygiene"), None)
    print(f"C-1 (Pós-Fix D4): hygiene_passed={hygiene_pillar_c1['passed'] if hygiene_pillar_c1 else False}")

    # D-5 pós-correção: Teste do Destilador Real
    reset_worktree()
    test_wal = FACTORY_DIR / "memory" / "distill_test_wal.jsonl"
    test_wal_content = (
        '{"session_id": "s1", "timestamp": "2026-10-04T14:47:00", "concept_id": "preflight-shortcuts", "raw_note": "Shortcuts are checked lexically without OS side-effects.", "status": "active"}\n'
        '{"session_id": "s2", "timestamp": "2026-10-04T14:51:00", "concept_id": "preflight-shortcuts", "raw_note": "Shortcuts are checked lexically without OS side-effects (duplicate).", "status": "active"}\n'
        '{"session_id": "s3", "timestamp": "2026-10-04T14:55:00", "concept_id": "plan-reachability", "raw_note": "Reachability follows next_step only.", "status": "active"}\n'
        '{"session_id": "s4", "timestamp": "2026-10-04T15:00:00", "concept_id": "plan-reachability-v2", "supersedes": "plan-reachability", "raw_note": "Reachability now supports conditional branching.", "status": "active"}\n'
    )
    test_wal.write_text(test_wal_content, encoding="utf-8")
    distill_res = memory_distillation_node({"raw_memories_path": str(test_wal)})
    results["D-5_Distillation"] = distill_res
    print(f"D-5 (Pós-Fix D5): active_concepts={distill_res.get('active_memories_used')}, total_distilled={distill_res.get('distilled_concepts_count')}")
    test_wal.unlink(missing_ok=True)

    reset_worktree()
    summary_file = OUTPUT_DIR / "round2_summary.json"
    summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n✅ Rodada 2 concluída com sucesso!")
    return results


if __name__ == "__main__":
    run_round2()
