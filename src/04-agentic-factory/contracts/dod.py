"""Contratos para a Definition of Done (DoD) e Veredito do DeepAgent Judge."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class DoDPillar(BaseModel):
    """Representa a avaliação de um pilar individual da Definition of Done."""

    name: str = Field(description="Identificador do pilar (ex: contract, tests, sonarqube, hygiene, memory)")
    passed: bool = Field(description="Se o pilar atingiu 100% dos critérios objetivos")
    evidence: str = Field(description="Evidência observável resumida")
    details: List[str] = Field(default_factory=list, description="Lista de apontamentos ou verificações individuais")


class DoDReport(BaseModel):
    """Scorecard consolidado da Definition of Done para a feature."""

    feature_name: str = Field(description="Nome da feature sendo auditada")
    all_passed: bool = Field(description="Verdadeiro se todos os 5 pilares foram aprovados")
    pillars: List[DoDPillar] = Field(default_factory=list, description="Lista de pilares avaliados")
    ready_for_human_acceptance: bool = Field(
        default=False, description="Se True, a DoD automatizada está completa e pronta para o aceite humano"
    )
    summary_markdown: str = Field(default="", description="Relatório formatado em markdown para o gate HITL")


class ReviewFinding(BaseModel):
    """Apontamento de revisão emitido pelo DeepAgent Judge."""

    category: Literal["security", "performance"] = Field(
        description="Categoria: security (segurança) ou performance (recursos e concorrência)"
    )
    severity: Literal["blocker", "advisory"] = Field(
        description="blocker: exige reparo obrigatório; advisory: recomendação consultiva (não bloqueia)"
    )
    location: str = Field(description="Arquivo e linha ou função onde o problema foi identificado")
    problem: str = Field(description="Descrição técnica precisa da falha")
    remediation_suggestion: str = Field(description="Instrução cirúrgica de correção para o worker")


class JudgeVerdict(BaseModel):
    """Veredito estruturado emitido pelo painel de juízes especializados."""

    verdict: Literal["approved", "repair_required", "escalate_to_human"] = Field(
        description="approved: apto para DoD; repair_required: contém blockers; escalate_to_human: divergência técnica"
    )
    blockers: List[ReviewFinding] = Field(default_factory=list, description="Apenas falhas bloqueantes graves")
    advisories: List[ReviewFinding] = Field(default_factory=list, description="Notas consultivas que não geram reparo")
    summary_for_human: str = Field(default="", description="Dossiê de síntese para o operador humano")
