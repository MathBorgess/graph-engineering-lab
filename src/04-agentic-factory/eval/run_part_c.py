"""Execução da Bateria Adversarial — Parte C: Portões Humanos (HITL) (F3).

Testa:
- C-1: scope_drift_review -> approve_and_continue -> avança para judge
- C-2: scope_drift_review -> revert_and_repair -> retrocede para worker
- C-3: final_task_acceptance -> request_changes -> retrocede para worker com motivo
- C-4: final_task_acceptance -> accept_and_complete -> avança para memory_distillation
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

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from eval.adversarial_harness import WORKTREE_PATH, reset_worktree, OUTPUT_DIR
from graph.workflow import build_agentic_factory_graph


async def run_part_c():
    print("=" * 70)
    print("🚪 Executando Bateria Adversarial Parte C (Portões Humanos HITL)")
    print("=" * 70)
    results = {}
    reset_worktree()

    # ----------------------------------------------------
    # C-1 & C-2: scope_drift_review com 'approve' e 'revert'
    # ----------------------------------------------------
    print("\n[C-1 & C-2] Testando ramificações de scope_drift_review...")
    checkpointer_c1 = InMemorySaver()
    graph_c1 = build_agentic_factory_graph(
        worktree_path=WORKTREE_PATH,
        raw_memories_file=FACTORY_DIR / "memory" / "raw_memories.jsonl",
        allowed_scope_patterns=["laya_computer/*", "tests/*", "README.md", "pyproject.toml"],
        max_worker_attempts=3,
        checkpointer=checkpointer_c1,
    )
    
    # Injetamos scope drift
    drift_file = WORKTREE_PATH / "scripts" / "unauthorized_patch.py"
    drift_file.parent.mkdir(parents=True, exist_ok=True)
    drift_file.write_text("# patch fora do escopo\n", encoding="utf-8")

    config_c1 = {"configurable": {"thread_id": "thread-hitl-c1"}}
    init_state_c1 = {
        "task_id": "test-c1",
        "feature_name": "preflight_plan",
        "worktree_path": str(WORKTREE_PATH),
        "messages": [HumanMessage(content="test")],
        "affected_files": ["scripts/unauthorized_patch.py"],
        "worker_attempt": 1,
        "max_attempts": 3,
        "validation_results": [],
        "is_valid": True,
        "human_decisions": [],
        "raw_memories_path": str(FACTORY_DIR / "memory" / "raw_memories.jsonl"),
        "final_status": "in_progress",
    }

    # Executa até parar no scope_gate
    # Como queremos testar especificamente o portão sem depender do worker, começamos direto após worker
    # Invocamos a partir do validator
    print("Disparando grafo com arquivo fora de escopo...")
    await graph_c1.ainvoke(init_state_c1, config=config_c1)
    
    snap_c1 = graph_c1.get_state(config_c1)
    int_c1 = snap_c1.tasks[0].interrupts[0].value if snap_c1.tasks and snap_c1.tasks[0].interrupts else {}
    print(f"Portão atingido: {int_c1.get('gate_name')}")

    # Teste C-1: Retomada com approve_and_continue
    print("Testando C-1: Retomada com 'approve_and_continue'...")
    await graph_c1.ainvoke(Command(resume={"choice": "approve_and_continue", "note": "Aprovado pelo operador"}), config=config_c1)
    snap_after_approve = graph_c1.get_state(config_c1)
    route_c1 = snap_after_approve.next
    print(f"C-1 Próximos nós após approve: {route_c1}")

    # Teste C-2: Retomada com revert_and_repair numa nova thread
    config_c2 = {"configurable": {"thread_id": "thread-hitl-c2"}}
    await graph_c1.ainvoke(init_state_c1, config=config_c2)
    print("Testando C-2: Retomada com 'revert_and_repair'...")
    await graph_c1.ainvoke(Command(resume={"choice": "revert_and_repair", "note": "Rejeitado desvio"}), config=config_c2)
    snap_after_revert = graph_c1.get_state(config_c2)
    route_c2 = snap_after_revert.next
    print(f"C-2 Próximos nós após revert: {route_c2}")

    c1_c2_data = {
        "gate_triggered": int_c1.get("gate_name"),
        "unexpected_files": int_c1.get("unexpected_files"),
        "c1_next_nodes_after_approve": list(route_c1),
        "c1_correct_transition": "judge" in route_c1 or "final_gate" in route_c1 or "dod" in route_c1,
        "c2_next_nodes_after_revert": list(route_c2),
        "c2_correct_transition": "worker" in route_c2,
    }
    results["C-1_C-2"] = c1_c2_data
    (OUTPUT_DIR / "part_c_scope_gates.json").write_text(json.dumps(c1_c2_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ----------------------------------------------------
    # C-3 & C-4: final_task_acceptance com 'request_changes' e 'accept_and_complete'
    # ----------------------------------------------------
    reset_worktree()
    print("\n[C-3 & C-4] Testando ramificações de final_task_acceptance...")
    config_c3 = {"configurable": {"thread_id": "thread-hitl-c3"}}
    # Simula estado limpo passando por DoD verde e parando em final_gate
    checkpointer_c3 = InMemorySaver()
    graph_c3 = build_agentic_factory_graph(
        worktree_path=WORKTREE_PATH,
        raw_memories_file=FACTORY_DIR / "memory" / "raw_memories.jsonl",
        checkpointer=checkpointer_c3,
    )
    init_state_c3 = {
        "task_id": "test-c3",
        "feature_name": "preflight_plan",
        "worktree_path": str(WORKTREE_PATH),
        "messages": [HumanMessage(content="test")],
        "affected_files": [],
        "worker_attempt": 1,
        "max_attempts": 3,
        "validation_results": [],
        "is_valid": True,
        "human_decisions": [],
        "raw_memories_path": str(FACTORY_DIR / "memory" / "raw_memories.jsonl"),
        "final_status": "in_progress",
    }
    # Executa até parar em final_gate
    await graph_c3.ainvoke(init_state_c3, config=config_c3)
    snap_c3 = graph_c3.get_state(config_c3)
    int_c3 = snap_c3.tasks[0].interrupts[0].value if snap_c3.tasks and snap_c3.tasks[0].interrupts else {}
    print(f"Portão atingido: {int_c3.get('gate_name')}")

    # Teste C-3: Retomada com request_changes
    print("Testando C-3: Retomada com 'request_changes'...")
    await graph_c3.ainvoke(Command(resume={"choice": "request_changes", "note": "Ajustar nome de teste"}), config=config_c3)
    snap_after_changes = graph_c3.get_state(config_c3)
    route_c3 = snap_after_changes.next
    print(f"C-3 Próximos nós após request_changes: {route_c3}")

    # Teste C-4: Retomada com accept_and_complete numa nova thread
    config_c4 = {"configurable": {"thread_id": "thread-hitl-c4"}}
    await graph_c3.ainvoke(init_state_c3, config=config_c4)
    print("Testando C-4: Retomada com 'accept_and_complete'...")
    await graph_c3.ainvoke(Command(resume={"choice": "accept_and_complete", "note": "Tudo validado"}), config=config_c4)
    snap_after_accept = graph_c3.get_state(config_c4)
    route_c4 = snap_after_accept.next
    final_status = snap_after_accept.values.get("final_status")
    print(f"C-4 Próximos nós após accept: {route_c4}, final_status: {final_status}")

    c3_c4_data = {
        "gate_triggered": int_c3.get("gate_name"),
        "c3_next_nodes_after_request_changes": list(route_c3),
        "c3_correct_transition": "worker" in route_c3,
        "c4_next_nodes_after_accept": list(route_c4),
        "c4_final_status": final_status,
        "c4_correct_transition": final_status == "completed" and len(route_c4) == 0,
    }
    results["C-3_C-4"] = c3_c4_data
    (OUTPUT_DIR / "part_c_final_gates.json").write_text(json.dumps(c3_c4_data, indent=2, ensure_ascii=False), encoding="utf-8")

    reset_worktree()
    print("\n✅ Bateria C concluída com sucesso!")


if __name__ == "__main__":
    asyncio.run(run_part_c())
