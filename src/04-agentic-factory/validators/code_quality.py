"""Validador de qualidade de código: execução de pytest e ruff com sanitização de logs."""

import subprocess
import sys
from pathlib import Path
from typing import Optional
try:
    from ..contracts.findings import Issue, ValidationResult
except (ImportError, ValueError):
    from contracts.findings import Issue, ValidationResult


def run_code_tests(
    worktree_path: Path,
    test_subpath: str = "tests",
    timeout_seconds: int = 120,
) -> ValidationResult:
    """Executa a suíte de testes pytest no worktree e classifica em pass, fail ou unverified."""
    worktree = worktree_path.resolve()
    target_dir = worktree / test_subpath

    if not target_dir.exists():
        return ValidationResult(
            validator_name="code_quality_tests",
            status="unverified",
            command_or_rule=f"pytest {test_subpath}",
            exit_code=2,
            details=f"Pasta de testes '{test_subpath}' não encontrada em {worktree}.",
            requires_interrupt=False,
            issues=[
                Issue(
                    code="TEST_SUITE_MISSING",
                    category="bug",
                    severity="critical",
                    message=f"Diretório de testes '{test_subpath}' não existe.",
                )
            ],
        )

    import shutil
    worktree_pytest = worktree / ".venv" / "bin" / "pytest"
    if worktree_pytest.exists():
        cmd = [str(worktree_pytest), "-q", "-rs", test_subpath]
    elif shutil.which("uv") and (worktree / "pyproject.toml").exists():
        cmd = ["uv", "run", "pytest", "-q", "-rs", test_subpath]
    else:
        cmd = [sys.executable, "-m", "pytest", "-q", "-rs", test_subpath]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ValidationResult(
            validator_name="code_quality_tests",
            status="unverified",
            command_or_rule=" ".join(cmd),
            exit_code=124,
            details=f"Execução do pytest excedeu o tempo limite de {timeout_seconds}s.",
            requires_interrupt=False,
            issues=[
                Issue(
                    code="TEST_TIMEOUT",
                    category="bug",
                    severity="critical",
                    message=f"Timeout ({timeout_seconds}s) na execução da suíte de testes.",
                )
            ],
        )
    except Exception as e:
        return ValidationResult(
            validator_name="code_quality_tests",
            status="unverified",
            command_or_rule=" ".join(cmd),
            exit_code=1,
            details=f"Falha de ambiente ao disparar subprocesso do pytest: {e}",
            requires_interrupt=False,
            issues=[],
        )

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if proc.returncode == 0:
        # Checagem Anti-Cheat / Tampering: se houver teste pulado ou desativado, veta a aprovação
        if "skipped" in stdout.lower() or "skipping" in stdout.lower():
            return ValidationResult(
                validator_name="code_quality_tests",
                status="fail",
                command_or_rule=" ".join(cmd),
                exit_code=1,
                details=f"Testes foram ignorados ou desativados com skip na suíte:\n{stdout[:400]}",
                requires_interrupt=False,
                issues=[
                    Issue(
                        code="TEST_TAMPERING_DETECTED",
                        category="security_hotspot",
                        severity="blocker",
                        message="Testes foram desativados com @pytest.mark.skip ou marcação de skip na suíte.",
                        suggestion="Remova marcações de skip e garanta que 100% dos testes sejam executados.",
                    )
                ],
            )

        return ValidationResult(
            validator_name="code_quality_tests",
            status="pass",
            command_or_rule=" ".join(cmd),
            exit_code=0,
            details=f"Testes passaram com sucesso:\n{stdout[:400]}",
            requires_interrupt=False,
            issues=[],
        )

    # Houve falhas no pytest
    return ValidationResult(
        validator_name="code_quality_tests",
        status="fail",
        command_or_rule=" ".join(cmd),
        exit_code=proc.returncode,
        details=f"Falha nos testes (exit code {proc.returncode}):\n{stdout[:800]}\n{stderr[:400]}",
        requires_interrupt=False,
        issues=[
            Issue(
                code="PYTEST_FAILURE",
                category="bug",
                severity="blocker",
                message="Um ou mais testes automatizados falharam no worktree.",
                suggestion="Revisar as mensagens de falha e corrigir a implementação no código.",
            )
        ],
    )
