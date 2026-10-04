"""Contratos de findings, resultados de validação e avaliações de risco."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class Issue(BaseModel):
    """Representa um apontamento estruturado no estilo SonarQube encontrado por um validator ou analyzer."""

    code: str = Field(description="Código estável da regra, ex: HARDCODED_SECRET, EXCESSIVE_COMPLEXITY")
    category: Literal["bug", "vulnerability", "code_smell", "security_hotspot"] = Field(
        default="code_smell",
        description="Categoria Sonar: bug (confiabilidade), vulnerability (segurança), code_smell (manutenibilidade), security_hotspot (revisão manual)",
    )
    severity: Literal["blocker", "critical", "major", "minor", "info"] = Field(
        default="major",
        description="Gravidade: blocker/critical (veto), major/minor (aviso), info (informativo)",
    )
    file_path: Optional[str] = Field(default=None, description="Arquivo onde o problema foi detectado")
    line_number: Optional[int] = Field(default=None, description="Linha do código associada")
    step_id: Optional[str] = Field(default=None, description="Identificador do passo associado no plano (se aplicável)")
    message: str = Field(description="Descrição objetiva do problema")
    suggestion: Optional[str] = Field(default=None, description="Sugestão de correção recomendada")


class ValidationResult(BaseModel):
    """Resultado formal da execução de um validator programático."""

    validator_name: str = Field(description="Nome do validador (ex: scope, static_code_analysis, mcp_contract, pytest)")
    status: Literal["pass", "fail", "unverified"] = Field(
        description="pass: passou; fail: reprovou determinístico; unverified: falha de ambiente/inconclusivo"
    )
    command_or_rule: str = Field(description="Comando executado ou regra avaliada")
    exit_code: int = Field(default=0, description="Código de saída do comando (0 para sucesso)")
    details: str = Field(default="", description="Sumário sanitizado da saída ou erro")
    artifact_path: Optional[str] = Field(default=None, description="Caminho do log completo em disco")
    requires_interrupt: bool = Field(default=False, description="Se True, solicita um portão de revisão humana HITL")
    issues: List[Issue] = Field(default_factory=list, description="Lista de issues estruturadas encontradas")


class RiskAssessment(BaseModel):
    """Classificação de risco para decisões de portão HITL."""

    level: Literal["routine", "needs_human", "blocked"] = Field(
        description="routine: operação em sandbox; needs_human: mudança de contrato/risco; blocked: violação grave"
    )
    risk_factors: List[str] = Field(default_factory=list, description="Fatores de risco identificados")
    rationale: str = Field(default="", description="Justificativa técnica da classificação")


class HumanDecision(BaseModel):
    """Registro de decisão humana em um ponto de interrupção (HITL)."""

    action_type: Literal["approve", "reject", "request_changes"] = Field(
        description="Decisão tomada pelo operador humano"
    )
    gate_name: str = Field(description="Identificador do gate (ex: contract_review, risk_gate, memory_gate)")
    actor: str = Field(default="human_operator", description="Identificador do revisor")
    note: str = Field(default="", description="Comentários, diretivas ou correções solicitadas")
    timestamp: Optional[str] = Field(default=None, description="Timestamp ISO da decisão")
