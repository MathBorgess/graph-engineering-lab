"""Validador O5: Integridade Estrita da Suíte de Testes (Anti-Tampering).

Portão Duro TEST_SUITE_INTEGRITY:
1. Linha de base prévia: IDs de `pytest --collect-only -q`, contagem de asserts por função (AST),
   hash SHA-256 de cada arquivo de teste existente e contagem de skips/xfails.
2. Execução via JUnit XML (`--junitxml`), nunca apenas pelo stdout.
3. Veto imediato se:
   - Teste antigo sumiu ou arquivo teve hash alterado.
   - Contagem de asserts em função de teste existente caiu.
   - Marcadores de skip, skipif ou xfail aumentaram.
   - Número de testes executados no JUnit XML é menor que a linha de base.
"""

import ast
import hashlib
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    from ..contracts.findings import Issue, ValidationResult
except (ImportError, ValueError):
    from contracts.findings import Issue, ValidationResult


@dataclass
class SuiteBaseline:
    worktree_path: str
    test_ids: List[str]
    file_hashes: Dict[str, str]
    function_asserts: Dict[str, int]
    skip_markers_count: int
    xfail_markers_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_pytest_executable(worktree: Path) -> List[str]:
    worktree_pytest = worktree / ".venv" / "bin" / "pytest"
    if worktree_pytest.exists():
        return [str(worktree_pytest)]
    import shutil
    if shutil.which("uv") and (worktree / "pyproject.toml").exists():
        return ["uv", "run", "pytest"]
    return [sys.executable, "-m", "pytest"]


def take_test_suite_baseline(worktree_path: Path, test_subpath: str = "tests") -> SuiteBaseline:
    """Extrai a linha de base de integridade da suíte antes do worker rodar."""
    worktree = worktree_path.resolve()
    target_dir = worktree / test_subpath
    if not target_dir.exists():
        raise FileNotFoundError(f"Diretório de testes {target_dir} não existe.")

    # 1. Coleta IDs de teste
    cmd = _get_pytest_executable(worktree) + ["--collect-only", "-q", test_subpath]
    proc = subprocess.run(cmd, cwd=str(worktree), capture_output=True, text=True, check=False)
    test_ids = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "::" in line and not line.startswith("="):
            test_ids.append(line)

    # 2. Hash e AST dos arquivos de teste existentes
    file_hashes: Dict[str, str] = {}
    function_asserts: Dict[str, int] = {}
    total_skips = 0
    total_xfails = 0

    for py_file in sorted(target_dir.glob("**/*.py")):
        rel_path = str(py_file.relative_to(worktree))
        content = py_file.read_bytes()
        file_hashes[rel_path] = hashlib.sha256(content).hexdigest()

        try:
            tree = ast.parse(content.decode("utf-8"), filename=str(py_file))
        except Exception:
            continue

        for node in ast.walk(tree):
            # Conta decoradores skip / xfail
            if isinstance(node, ast.FunctionDef):
                fn_key = f"{rel_path}::{node.name}"
                # Conta asserts na função
                assert_count = sum(1 for child in ast.walk(node) if isinstance(child, ast.Assert))
                function_asserts[fn_key] = assert_count

                for decorator in node.decorator_list:
                    dec_str = ast.dump(decorator)
                    if "skip" in dec_str:
                        total_skips += 1
                    if "xfail" in dec_str:
                        total_xfails += 1

    return SuiteBaseline(
        worktree_path=str(worktree),
        test_ids=sorted(test_ids),
        file_hashes=file_hashes,
        function_asserts=function_asserts,
        skip_markers_count=total_skips,
        xfail_markers_count=total_xfails,
    )


def verify_test_suite_integrity(
    worktree_path: Path,
    baseline: SuiteBaseline,
    test_subpath: str = "tests",
    timeout_seconds: int = 120,
) -> ValidationResult:
    """Executa a suíte via JUnit XML e compara contra a linha de base para portão TEST_SUITE_INTEGRITY."""
    worktree = worktree_path.resolve()
    target_dir = worktree / test_subpath
    issues: List[Issue] = []

    # 1. Checagem estática de arquivos de teste pré-existentes
    for rel_path, expected_hash in baseline.file_hashes.items():
        curr_file = worktree / rel_path
        if not curr_file.exists():
            issues.append(
                Issue(
                    code="TEST_FILE_DELETED",
                    category="security_hotspot",
                    severity="blocker",
                    file_path=rel_path,
                    message=f"Arquivo de teste pré-existente foi apagado: {rel_path}",
                    suggestion="Restaurar o arquivo de teste original. O worker só pode criar novos arquivos de teste.",
                )
            )
            continue

        curr_bytes = curr_file.read_bytes()
        curr_hash = hashlib.sha256(curr_bytes).hexdigest()
        if curr_hash != expected_hash:
            issues.append(
                Issue(
                    code="TEST_FILE_MODIFIED",
                    category="security_hotspot",
                    severity="blocker",
                    file_path=rel_path,
                    message=f"Arquivo de teste pré-existente foi modificado (hash mismatch): {rel_path}",
                    suggestion="Arquivos de teste existentes são somente-leitura. Reverter alterações.",
                )
            )

    # 2. Checagem AST pós-alteração (Asserts e Marcadores de Skip)
    current_fn_asserts: Dict[str, int] = {}
    current_skips = 0
    current_xfails = 0

    for py_file in sorted(target_dir.glob("**/*.py")):
        rel_path = str(py_file.relative_to(worktree))
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                fn_key = f"{rel_path}::{node.name}"
                assert_count = sum(1 for child in ast.walk(node) if isinstance(child, ast.Assert))
                current_fn_asserts[fn_key] = assert_count

                for decorator in node.decorator_list:
                    dec_str = ast.dump(decorator)
                    if "skip" in dec_str:
                        current_skips += 1
                    if "xfail" in dec_str:
                        current_xfails += 1

    # Verifica se asserts em testes da baseline foram reduzidos
    for fn_key, orig_asserts in baseline.function_asserts.items():
        if fn_key in current_fn_asserts:
            curr_asserts = current_fn_asserts[fn_key]
            if curr_asserts < orig_asserts:
                issues.append(
                    Issue(
                        code="ASSERTION_REMOVED",
                        category="security_hotspot",
                        severity="blocker",
                        message=f"Contagem de asserts caiu em '{fn_key}': {orig_asserts} -> {curr_asserts}",
                        suggestion="Restaurar as asserções originais. Test tampering é proibido.",
                    )
                )

    # Verifica se skips ou xfails aumentaram
    if current_skips > baseline.skip_markers_count:
        issues.append(
            Issue(
                code="TEST_TAMPERING_SKIP",
                category="security_hotspot",
                severity="blocker",
                message=f"Novos marcadores @pytest.mark.skip detectados na suíte: {baseline.skip_markers_count} -> {current_skips}",
                suggestion="Remover marcações de skip.",
            )
        )
    if current_xfails > baseline.xfail_markers_count:
        issues.append(
            Issue(
                code="TEST_TAMPERING_XFAIL",
                category="security_hotspot",
                severity="blocker",
                message=f"Novos marcadores @pytest.mark.xfail detectados na suíte: {baseline.xfail_markers_count} -> {current_xfails}",
                suggestion="Remover marcações de xfail.",
            )
        )

    # 3. Execução do Pytest com --junitxml
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp_xml:
        xml_path = Path(tmp_xml.name)

    cmd = _get_pytest_executable(worktree) + ["--junitxml", str(xml_path), "-q", test_subpath]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        xml_path.unlink(missing_ok=True)
        return ValidationResult(
            validator_name="test_suite_integrity",
            status="unverified",
            command_or_rule=" ".join(cmd),
            exit_code=124,
            details="Timeout na execução dos testes.",
            requires_interrupt=False,
            issues=[Issue(code="TEST_TIMEOUT", severity="critical", message="Timeout no pytest")],
        )

    # 4. Leitura do JUnit XML
    total_executed = 0
    failures_count = 0
    errors_count = 0
    skipped_count = 0

    if xml_path.exists() and xml_path.stat().st_size > 0:
        try:
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            # Se a raiz for testsuites ou testsuite
            suite_node = root if root.tag == "testsuite" else root.find("testsuite")
            if suite_node is not None:
                total_executed = int(suite_node.attrib.get("tests", 0))
                failures_count = int(suite_node.attrib.get("failures", 0))
                errors_count = int(suite_node.attrib.get("errors", 0))
                skipped_count = int(suite_node.attrib.get("skipped", 0))
            else:
                total_executed = sum(int(s.attrib.get("tests", 0)) for s in root.findall("testsuite"))
                failures_count = sum(int(s.attrib.get("failures", 0)) for s in root.findall("testsuite"))
                errors_count = sum(int(s.attrib.get("errors", 0)) for s in root.findall("testsuite"))
                skipped_count = sum(int(s.attrib.get("skipped", 0)) for s in root.findall("testsuite"))
        except Exception as e:
            issues.append(Issue(code="JUNIT_XML_PARSE_ERROR", severity="blocker", message=f"Erro ao ler JUnit XML: {e}"))
        finally:
            xml_path.unlink(missing_ok=True)
    else:
        xml_path.unlink(missing_ok=True)
        issues.append(Issue(code="JUNIT_XML_MISSING", severity="blocker", message="Arquivo JUnit XML não foi gerado pelo pytest."))

    # Veto se contagem de testes executados for menor que a baseline coletada
    if total_executed < len(baseline.test_ids):
        issues.append(
            Issue(
                code="TEST_COUNT_DEFICIT",
                category="security_hotspot",
                severity="blocker",
                message=f"Total de testes executados ({total_executed}) é menor que a linha de base ({len(baseline.test_ids)}).",
                suggestion="Todos os testes da linha de base devem ser executados.",
            )
        )

    if skipped_count > 0:
        issues.append(
            Issue(
                code="TEST_SKIPPED_IN_RUN",
                category="security_hotspot",
                severity="blocker",
                message=f"O JUnit XML registrou {skipped_count} teste(s) pulado(s) durante a execução.",
                suggestion="Remover marcações de skip.",
            )
        )

    if failures_count > 0 or errors_count > 0 or proc.returncode != 0:
        issues.append(
            Issue(
                code="UNIT_TEST_FAILURES",
                category="bug",
                severity="blocker",
                message=f"Falha na suíte de testes: {failures_count} failures, {errors_count} errors (returncode {proc.returncode}).",
                suggestion="Corrigir o código para que 100% dos testes passem.",
            )
        )

    has_blockers = any(i.severity in ("blocker", "critical") for i in issues)
    status = "fail" if has_blockers else "pass"
    details = f"JUnit XML: {total_executed} executados, {failures_count} falhas, {skipped_count} skips. Issues: {len(issues)}"

    return ValidationResult(
        validator_name="test_suite_integrity",
        status=status,
        command_or_rule="pytest --junitxml [O5 Suite Integrity]",
        exit_code=proc.returncode if has_blockers else 0,
        details=details,
        requires_interrupt=False,
        issues=issues,
    )
