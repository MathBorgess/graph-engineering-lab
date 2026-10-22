"""Tools determinísticas e mutantes do Assistente de Operações integradas ao Sandbox SQLite."""

import uuid
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from voice_lab.contracts.state import ToolResult
from voice_lab.skills.policy_knowledge import get_policy
from voice_lab.tools.sandbox import sandbox, JobRecord


@tool
def lookup_policy(topic: str) -> Dict[str, Any]:
    """Consulta regras operacionais, definições de vocabulário e políticas do laboratório (ex: barge_in, confirmacao, s2s, cascata)."""
    return get_policy(topic)


@tool
def list_jobs(status_filter: Optional[str] = None) -> Dict[str, Any]:
    """Consulta o status dos experimentos e jobs registrados no sandbox SQLite do laboratório."""
    jobs = sandbox.list_jobs(status_filter=status_filter)
    
    jobs_dicts = [j.model_dump() for j in jobs]
    return {
        "total": len(jobs_dicts),
        "jobs": jobs_dicts,
        "status_filter": status_filter
    }


def execute_trigger_experiment(experiment_id: str, profile: str, idempotency_key: Optional[str] = None) -> ToolResult:
    """Dispara um experimento no sandbox SQLite com garantia de idempotência."""
    if not idempotency_key:
        raise ValueError("A stable idempotency_key is required before execution")
    key = idempotency_key
    record, is_new = sandbox.trigger_job(experiment_id, profile, idempotency_key=key)
    
    status_msg = "disparado com sucesso" if is_new else "já estava em execução (idempotência respeitada)"
    return ToolResult(
        tool_name="trigger_experiment",
        status="success",
        data={
            "job_id": record.job_id,
            "experiment": record.experiment_id,
            "profile": record.profile,
            "status": record.status,
            "is_new": is_new,
            "message": f"Experimento '{record.experiment_id}' {status_msg} sob o perfil '{record.profile}'. Job ID: {record.job_id}."
        }
    )


def execute_cancel_experiment(job_id: str, reason: str = "Solicitado pelo usuário", idempotency_key: Optional[str] = None) -> ToolResult:
    """Executa a transação compensatória SAGA de cancelamento de um job no sandbox SQLite."""
    key = idempotency_key or f"cancel_{job_id}_{uuid.uuid4().hex[:4]}"
    record, was_cancelled = sandbox.cancel_job(job_id, reason=reason, idempotency_key=key)
    
    if not record:
        return ToolResult(
            tool_name="cancel_experiment",
            status="failure",
            error=f"Job com identificador '{job_id}' não foi encontrado no sandbox."
        )
        
    return ToolResult(
        tool_name="cancel_experiment",
        status="success",
        data={
            "job_id": record.job_id,
            "experiment": record.experiment_id,
            "status": record.status,
            "was_cancelled": was_cancelled,
            "message": f"Job '{record.job_id}' cancelado com sucesso no sandbox (SAGA Compensation concluída)."
        }
    )
