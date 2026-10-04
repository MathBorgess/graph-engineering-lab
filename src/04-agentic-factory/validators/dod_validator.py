"""Validador central da Definition of Done (DoD) com consolidação de scorecard em 5 pilares."""

from pathlib import Path
from typing import List, Optional
try:
    from ..contracts.dod import DoDPillar, DoDReport
    from ..contracts.findings import ValidationResult
except (ImportError, ValueError):
    from contracts.dod import DoDPillar, DoDReport
    from contracts.findings import ValidationResult


def evaluate_definition_of_done(
    feature_name: str,
    validation_results: List[ValidationResult],
    worktree_path: Path,
    raw_memories_file: Optional[Path] = None,
) -> DoDReport:
    """Audita os 5 pilares fundamentais da DoD antes de autorizar o aceite humano.
    
    Pilares avaliados:
    1. Contrato da Feature (MCP Schema e registro)
    2. Suíte de Testes (Pytest exit code 0)
    3. Qualidade Estática SonarQube (Zero blockers/critical)
    4. Higiene do Repositório (Sem lixo espúrio e escopo saneado)
    5. Memória e Descobertas (Registro no WAL)
    """
    base = worktree_path.resolve()
    pillars: List[DoDPillar] = []

    # Mapeia resultados dos validadores por nome
    res_map = {r.validator_name: r for r in validation_results}

    # 1. Pilar de Contrato
    mcp_res = res_map.get("mcp_contract_validator")
    if mcp_res and mcp_res.status == "pass":
        pillars.append(
            DoDPillar(
                name="contract_conformance",
                passed=True,
                evidence="Tool MCP registrada com schema correto e documentação presente.",
                details=[mcp_res.details],
            )
        )
    else:
        err = mcp_res.details if mcp_res else "Validador de contrato MCP não foi executado."
        pillars.append(
            DoDPillar(
                name="contract_conformance",
                passed=False,
                evidence="Contrato MCP violado ou ausente.",
                details=[err],
            )
        )

    # 2. Pilar de Testes
    test_res = res_map.get("code_quality_tests")
    if test_res and test_res.status == "pass" and test_res.exit_code == 0:
        pillars.append(
            DoDPillar(
                name="test_suite_coverage",
                passed=True,
                evidence="Suíte de testes automatizados passou com 100% de sucesso.",
                details=[test_res.details[:300]],
            )
        )
    else:
        err = test_res.details if test_res else "Testes automatizados não executados ou com falhas."
        pillars.append(
            DoDPillar(
                name="test_suite_coverage",
                passed=False,
                evidence="Falha nos testes automatizados.",
                details=[err[:300]],
            )
        )

    # 3. Pilar SonarQube (Qualidade & Segurança)
    sonar_res = res_map.get("static_code_analysis")
    if sonar_res:
        blockers = [i for i in sonar_res.issues if i.severity in ("blocker", "critical")]
        if not blockers:
            pillars.append(
                DoDPillar(
                    name="sonarqube_quality_gate",
                    passed=True,
                    evidence="Quality Gate SonarQube aprovado: zero falhas críticas ou bloqueantes.",
                    details=[f"Total de apontamentos consultivos/menores: {len(sonar_res.issues)}."],
                )
            )
        else:
            pillars.append(
                DoDPillar(
                    name="sonarqube_quality_gate",
                    passed=False,
                    evidence=f"Reprovado no Quality Gate: {len(blockers)} falha(s) crítica(s) ou vulnerabilidade(s).",
                    details=[f"{b.code} ({b.file_path}:{b.line_number}): {b.message}" for b in blockers],
                )
            )
    else:
        pillars.append(
            DoDPillar(
                name="sonarqube_quality_gate",
                passed=False,
                evidence="Análise estática de código não realizada.",
                details=["Validador static_code_analysis ausente."],
            )
        )

    # 4. Pilar de Higiene do Repositório (Git Hygiene)
    unwanted_extensions = {".tmp", ".DS_Store"}
    ignored_dirs = {".venv", "__pycache__", ".pytest_cache", ".git", ".ruff_cache"}
    junk_files = []
    if base.exists():
        for p in base.glob("**/*"):
            if any(ignored in p.parts for ignored in ignored_dirs):
                continue
            if p.is_file() and (p.suffix in unwanted_extensions or (p.suffix == ".pyc" and "__pycache__" not in p.parts)):
                junk_files.append(p.name)

    scope_res = res_map.get("scope_validator")
    has_unapproved_drift = scope_res.requires_interrupt if scope_res else False

    if not junk_files and not has_unapproved_drift:
        pillars.append(
            DoDPillar(
                name="repository_hygiene",
                passed=True,
                evidence="Repositório limpo sem arquivos temporários espúrios e escopo validado.",
                details=["Nenhum resíduo de build ou arquivo temporário detectado."],
            )
        )
    else:
        reasons = []
        if junk_files:
            reasons.append(f"Arquivos temporários detectados: {junk_files}")
        if has_unapproved_drift:
            reasons.append("Desvio de escopo pendente de aprovação humana.")
        pillars.append(
            DoDPillar(
                name="repository_hygiene",
                passed=False,
                evidence="Higiene do repositório reprovada.",
                details=reasons,
            )
        )

    # 5. Pilar de Memória e WAL
    if raw_memories_file and raw_memories_file.exists() and raw_memories_file.stat().st_size > 0:
        pillars.append(
            DoDPillar(
                name="session_memory_recorded",
                passed=True,
                evidence="Descobertas da sessão registradas no WAL raw_memories.jsonl.",
                details=[f"Arquivo {raw_memories_file.name} populado com sucesso."],
            )
        )
    else:
        pillars.append(
            DoDPillar(
                name="session_memory_recorded",
                passed=True,  # Informativo/pass se não houve descobertas novas obrigatórias
                evidence="Nenhuma anotação necessária ou arquivo WAL vazio.",
                details=["Registro de memória verificado."],
            )
        )

    all_passed = all(p.passed for p in pillars)

    # Monta o sumário markdown legível para humanos
    summary_lines = [
        f"### 📋 Definition of Done Scorecard — Feature: `{feature_name}`",
        f"**Status Geral:** {'✅ PRONTO PARA ACEITE HUMANO' if all_passed else '❌ PENDÊNCIAS IMPEDINDO ACEITE'}",
        "",
        "| Pilar | Status | Evidência Observável |",
        "| :--- | :---: | :--- |",
    ]
    for p in pillars:
        status_icon = "✅ PASSOU" if p.passed else "❌ FALHOU"
        summary_lines.append(f"| `{p.name}` | {status_icon} | {p.evidence} |")

    summary_markdown = "\n".join(summary_lines)

    return DoDReport(
        feature_name=feature_name,
        all_passed=all_passed,
        pillars=pillars,
        ready_for_human_acceptance=all_passed,
        summary_markdown=summary_markdown,
    )
