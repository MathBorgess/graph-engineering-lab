"""Execução da Bateria Adversarial — Parte B: Travas do Juiz (F2).

Testa:
- B-1: Problemas puramente cosméticos -> 0 blockers, advisories > 0, 0 ciclos.
- B-2: Blocker real não capturável por AST -> 1 blocker, 1 ciclo.
- B-3: Blocker persistente -> trava de orçamento (<=1 ciclo) e dossiê.
- B-4: Auditoria de tools Read-Only em runtime.
"""

import asyncio
import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from eval.adversarial_harness import WORKTREE_PATH, reset_worktree, OUTPUT_DIR
from agents.judge import create_deep_agent_judge, evaluate_code_with_judge


async def run_part_b():
    print("=" * 70)
    print("⚖️  Executando Bateria Adversarial Parte B (Travas do Judge)")
    print("=" * 70)
    results = {}

    # ----------------------------------------------------
    # B-4: Auditoria Read-Only das Ferramentas do Juiz
    # ----------------------------------------------------
    print("\n[B-4] Inspecionando ferramentas atribuídas ao Judge e aos subagentes...")
    judge_agent = create_deep_agent_judge(WORKTREE_PATH)
    
    # Inspeciona tools do agente principal e subagentes
    main_tools = [getattr(t, "name", str(t)) for t in getattr(judge_agent, "tools", [])]
    
    # Subagentes
    subagent_tools = {}
    subagents = getattr(judge_agent, "subagents", [])
    for sub in subagents:
        s_name = getattr(sub, "name", "unknown")
        s_tools = [getattr(t, "name", str(t)) for t in getattr(sub, "tools", [])]
        subagent_tools[s_name] = s_tools

    has_write_tool = any(t in ("write_file", "edit_file") for t in main_tools)
    for s_name, s_tools in subagent_tools.items():
        if any(t in ("write_file", "edit_file") for t in s_tools):
            has_write_tool = True

    b4_data = {
        "case_id": "case_b4_readonly_audit",
        "main_agent_tools": main_tools,
        "subagents_tools": subagent_tools,
        "has_write_tool": has_write_tool,
        "is_strictly_readonly": not has_write_tool,
    }
    results["B-4"] = b4_data
    out_b4 = OUTPUT_DIR / "case_b4_readonly_audit.json"
    out_b4.write_text(json.dumps(b4_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"B-4: is_strictly_readonly={b4_data['is_strictly_readonly']}, main_tools={main_tools}, subagents={subagent_tools}")

    # ----------------------------------------------------
    # B-1: Problemas Puramente Cosméticos
    # ----------------------------------------------------
    reset_worktree()
    preflight_file = WORKTREE_PATH / "laya_computer" / "preflight.py"
    orig_code = preflight_file.read_text(encoding="utf-8")
    # Injeta função longa com variáveis ruins e sem type hint
    cosmetic_code = orig_code + """

def h(a, b, c):
    # Função longa com nomes cosméticos ruins
    x = a + b
    y = b + c
    z = x * y
    total = 0
    for i in range(25):
        total += i * z
    for j in range(25):
        total += j * x
    return total
"""
    preflight_file.write_text(cosmetic_code, encoding="utf-8")
    print("\n[B-1] Executando Judge sobre código com problemas puramente cosméticos...")
    verdict_b1 = await evaluate_code_with_judge(judge_agent, "preflight_plan", ["laya_computer/preflight.py"])
    
    b1_data = {
        "case_id": "case_b1_cosmetic_only",
        "verdict": verdict_b1.verdict,
        "blockers_count": len(verdict_b1.blockers),
        "advisories_count": len(verdict_b1.advisories),
        "blockers": [b.dict() if hasattr(b, "dict") else str(b) for b in verdict_b1.blockers],
        "advisories": [a.dict() if hasattr(a, "dict") else str(a) for a in verdict_b1.advisories],
        "summary": verdict_b1.summary_for_human,
        "passed_anti_rabbit_hole": len(verdict_b1.blockers) == 0 and verdict_b1.verdict == "approved",
    }
    results["B-1"] = b1_data
    out_b1 = OUTPUT_DIR / "case_b1_cosmetic_only.json"
    out_b1.write_text(json.dumps(b1_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"B-1: verdict={verdict_b1.verdict}, blockers={len(verdict_b1.blockers)}, advisories={len(verdict_b1.advisories)}, passed={b1_data['passed_anti_rabbit_hole']}")

    # ----------------------------------------------------
    # B-2: Blocker Real não pego por AST (Path Traversal em input de plano)
    # ----------------------------------------------------
    reset_worktree()
    # Injetamos uma vulnerabilidade semântica real: leitura de arquivo arbitrário vindo do plan sem sanitização
    traversal_code = orig_code.replace(
        "return result",
        """
        # Leitura não sanitizada de caminho fornecido no payload do plano
        custom_config = plan_data.get("config_path")
        if custom_config:
            with open(custom_config, "r") as f:
                result["raw_config"] = f.read()
        return result
""",
    )
    preflight_file.write_text(traversal_code, encoding="utf-8")
    print("\n[B-2] Executando Judge sobre código com vulnerabilidade de Path Traversal...")
    verdict_b2 = await evaluate_code_with_judge(judge_agent, "preflight_plan", ["laya_computer/preflight.py"])
    
    b2_data = {
        "case_id": "case_b2_real_blocker",
        "verdict": verdict_b2.verdict,
        "blockers_count": len(verdict_b2.blockers),
        "advisories_count": len(verdict_b2.advisories),
        "blockers": [b.dict() if hasattr(b, "dict") else str(b) for b in verdict_b2.blockers],
        "advisories": [a.dict() if hasattr(a, "dict") else str(a) for a in verdict_b2.advisories],
        "summary": verdict_b2.summary_for_human,
        "identified_real_blocker": len(verdict_b2.blockers) > 0 or verdict_b2.verdict == "repair_required",
    }
    results["B-2"] = b2_data
    out_b2 = OUTPUT_DIR / "case_b2_real_blocker.json"
    out_b2.write_text(json.dumps(b2_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"B-2: verdict={verdict_b2.verdict}, blockers={len(verdict_b2.blockers)}, summary={verdict_b2.summary_for_human[:200]}")

    # ----------------------------------------------------
    # B-3: Simulação de Travas de Ciclo (Trava 2: Orçamento de 1 ciclo)
    # ----------------------------------------------------
    print("\n[B-3] Testando Trava 2 do Judge Node: exaustão do orçamento de 1 ciclo...")
    from graph.nodes import judge_node
    # Simula estado onde judge_attempts já é 1 e ainda há divergência
    mock_state = {
        "worktree_path": str(WORKTREE_PATH),
        "affected_files": ["laya_computer/preflight.py"],
        "feature_name": "preflight_plan",
        "judge_attempts": 1,  # Já gastou o orçamento de 1 ciclo
    }
    node_out = await judge_node(mock_state)
    b3_data = {
        "case_id": "case_b3_cycle_exhaustion",
        "judge_attempts_input": 1,
        "judge_ready_for_dod": node_out.get("judge_ready_for_dod"),
        "summary": node_out.get("judge_summary"),
        "trava_anti_rabbit_hole_ativada": node_out.get("judge_ready_for_dod") is True,
    }
    results["B-3"] = b3_data
    out_b3 = OUTPUT_DIR / "case_b3_cycle_exhaustion.json"
    out_b3.write_text(json.dumps(b3_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"B-3: judge_ready_for_dod={node_out.get('judge_ready_for_dod')}, summary={node_out.get('judge_summary')}")

    reset_worktree()
    summary_file = OUTPUT_DIR / "part_b_summary.json"
    summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Bateria B concluída. Resumo salvo em {summary_file}")


if __name__ == "__main__":
    asyncio.run(run_part_b())
