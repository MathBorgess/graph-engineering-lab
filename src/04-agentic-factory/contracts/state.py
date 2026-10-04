"""Definição do FactoryState para o orquestrador LangGraph."""

import operator
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict
from .findings import HumanDecision, RiskAssessment, ValidationResult


class FactoryState(TypedDict):
    """Estado central compartilhado (Blackboard) do LangGraph.
    
    Regras de arquitetura:
    1. Mantém apenas ponteiros, identificadores e metadados leves.
    2. Logs volumosos, diffs extensos e memórias brutas ficam em disco.
    3. Redutores 'operator.add' garantem rastreabilidade sem sobrescrever histórico.
    """

    # 1. Identificação e Sandbox
    task_id: str
    feature_name: str
    worktree_path: str

    # 2. Conversação e Instruções do Grafo
    messages: Annotated[List[Dict[str, Any]], operator.add]

    # 3. Artefatos de Código Gerados pelo Worker
    diff_path: Optional[str]
    affected_files: List[str]

    # 4. Avaliação dos Validators Programáticos e Orçamento de Reparo
    worker_attempt: int
    max_attempts: int
    validation_results: List[ValidationResult]
    is_valid: bool

    # 5. Risco e Auditoria de Decisões HITL
    risk_assessment: Optional[RiskAssessment]
    human_decisions: Annotated[List[HumanDecision], operator.add]

    # 6. Memória Seletiva (Padrão WAL em disco)
    raw_memories_path: Optional[str]  # Caminho para o .jsonl em disco
    active_memories_used: List[str]   # Slugs das memórias ativas consultadas

    # 7. Relatórios de Avaliação do Judge e da Definition of Done (DoD)
    judge_summary: Optional[str]
    judge_attempts: Optional[int]
    judge_ready_for_dod: Optional[bool]
    dod_report: Optional[Any]
    dod_summary_markdown: Optional[str]
    ready_for_human_acceptance: Optional[bool]

    # 8. Desfecho da Execução
    final_status: Literal["in_progress", "completed", "failed", "rejected"]
