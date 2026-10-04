"""Validador de escopo não-bloqueante: solicita interrupção HITL se encontrar diff fora do escopo."""

from pathlib import Path
from typing import List, Set
try:
    from ..contracts.findings import Issue, ValidationResult
except (ImportError, ValueError):
    from contracts.findings import Issue, ValidationResult


def validate_diff_scope(
    affected_files: List[str],
    allowed_patterns: List[str],
) -> ValidationResult:
    """Verifica se os arquivos alterados estão dentro dos padrões autorizados.
    
    COMPORTAMENTO:
    - Não bloqueia a esteira diretamente com 'fail'.
    - Se encontrar arquivos inesperados, sinaliza 'requires_interrupt=True' e categoria 'security_hotspot'
      para que o operador humano decida no gate HITL se permite prosseguir ou retrocede (revert).
    """
    unexpected: Set[str] = set()
    normalized_affected = [f.strip().lstrip("/") for f in affected_files if f.strip()]

    for f in normalized_affected:
        # Checa se o arquivo casa com algum padrão permitido
        is_allowed = any(
            f == p.lstrip("/") or f.startswith(p.lstrip("/")) or Path(f).match(p)
            for p in allowed_patterns
        )
        if not is_allowed:
            unexpected.add(f)

    if not unexpected:
        return ValidationResult(
            validator_name="scope_validator",
            status="pass",
            command_or_rule="scope_whitelist_check",
            exit_code=0,
            details=f"Todos os {len(normalized_affected)} arquivos modificados estão dentro do escopo permitido.",
            requires_interrupt=False,
            issues=[],
        )

    # Identificou desvio de escopo: cria issue de Security Hotspot e solicita HITL
    issues = [
        Issue(
            code="SCOPE_DRIFT",
            category="security_hotspot",
            severity="critical",
            file_path=f,
            message=f"Arquivo '{f}' foi modificado mas está fora da lista autorizada de escopo.",
            suggestion="Validar no gate de revisão se a alteração é intencional ou se deve ser revertida (git checkout).",
        )
        for f in sorted(unexpected)
    ]

    return ValidationResult(
        validator_name="scope_validator",
        status="pass",  # Não bloqueia imediatamente com fail; encaminha para decisão humana
        command_or_rule="scope_whitelist_check",
        exit_code=0,
        details=f"Atenção: {len(unexpected)} arquivo(s) fora do escopo esperado. Interrupção humana solicitada.",
        requires_interrupt=True,
        issues=issues,
    )
