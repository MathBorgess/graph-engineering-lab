"""Portões de revisão humana (HITL Gates) construídos com a função interrupt() do LangGraph."""

from langgraph.types import interrupt
from typing import Dict, Any


def scope_review_gate(state: Dict[str, Any]) -> dict:
    """Portão HITL acionado quando o scope_validator detecta alterações fora da whitelist."""
    unexpected_files = []
    scope_res = next((r for r in state.get("validation_results", []) if r.validator_name == "scope_validator"), None)
    if scope_res:
        unexpected_files = [i.file_path for i in scope_res.issues if i.code == "SCOPE_DRIFT"]

    # Interrompe o grafo e aguarda decisão humana
    decision = interrupt({
        "gate_name": "scope_drift_review",
        "task_id": state.get("task_id"),
        "unexpected_files": unexpected_files,
        "message": f"Foram detectadas alterações em {len(unexpected_files)} arquivo(s) fora da whitelist.",
        "choices": ["approve_and_continue", "revert_and_repair"],
    })

    return {
        "human_decisions": [
            {
                "gate_name": "scope_drift_review",
                "action_type": decision.get("choice", "approve_and_continue"),
                "note": decision.get("note", ""),
            }
        ]
    }


def final_acceptance_gate(state: Dict[str, Any]) -> dict:
    """Portão HITL final acionado após a aprovação de todos os pilares da DoD e do Judge."""
    dod_summary = state.get("dod_summary_markdown", "DoD Scorecard não disponível.")
    judge_summary = state.get("judge_summary", "Revisão do Judge aprovada.")

    decision = interrupt({
        "gate_name": "final_task_acceptance",
        "task_id": state.get("task_id"),
        "feature_name": state.get("feature_name"),
        "dod_scorecard": dod_summary,
        "judge_summary": judge_summary,
        "diff_path": state.get("diff_path"),
        "message": "Todos os pilares da DoD automatizada e o Judge passaram. Decisão final de entrega requerida.",
        "choices": ["accept_and_complete", "request_changes", "reject"],
    })

    action = decision.get("choice", "accept_and_complete")
    final_status = "completed" if action == "accept_and_complete" else ("failed" if action == "reject" else "in_progress")

    return {
        "final_status": final_status,
        "human_decisions": [
            {
                "gate_name": "final_task_acceptance",
                "action_type": action,
                "note": decision.get("note", ""),
            }
        ],
    }
