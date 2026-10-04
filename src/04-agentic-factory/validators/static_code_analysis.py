"""Validador estático estilo SonarQube para análise de código Python (AST + Regras de Segurança)."""

import ast
from pathlib import Path
import re
from typing import List, Optional
try:
    from ..contracts.findings import Issue, ValidationResult
except (ImportError, ValueError):
    from contracts.findings import Issue, ValidationResult

# Padrões regex para detecção de segredos hardcoded
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*=\s*['\"][a-zA-Z0-9_\-\.]{8,}['\"]"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"ey[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}"),
]

# Funções perigosas proibidas
DANGEROUS_CALLS = {"eval", "exec", "__import__"}


class SonarQubeAstVisitor(ast.NodeVisitor):
    """Visita a árvore AST inspecionando bugs, vulnerabilidades, code smells e hotspots."""

    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.source_lines = source_code.splitlines()
        self.issues: List[Issue] = []
        self._current_nesting = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # 1. Code Smell: Tamanho excessivo da função (> 50 linhas)
        if hasattr(node, "end_lineno") and node.end_lineno:
            func_len = node.end_lineno - node.lineno
            if func_len > 50:
                self.issues.append(
                    Issue(
                        code="OVERSIZED_FUNCTION",
                        category="code_smell",
                        severity="minor",
                        file_path=self.file_path,
                        line_number=node.lineno,
                        message=f"Função '{node.name}' tem {func_len} linhas (limiar recomendado: 50).",
                        suggestion="Refatorar a função dividindo-a em funções auxiliares menores.",
                    )
                )

        # 2. Code Smell: Falta de type hint no retorno em funções públicas
        if not node.name.startswith("_") and node.returns is None:
            self.issues.append(
                Issue(
                    code="MISSING_RETURN_TYPE",
                    category="code_smell",
                    severity="minor",
                    file_path=self.file_path,
                    line_number=node.lineno,
                    message=f"Função pública '{node.name}' não possui anotação de tipo de retorno.",
                    suggestion="Adicionar anotação explícita de tipo de retorno (ex: -> dict ou -> None).",
                )
            )

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 3. Vulnerability: Chamadas perigosas de execução dinâmica (eval, exec)
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name in DANGEROUS_CALLS:
            self.issues.append(
                Issue(
                    code="DANGEROUS_DYNAMIC_EXECUTION",
                    category="vulnerability",
                    severity="blocker",
                    file_path=self.file_path,
                    line_number=node.lineno,
                    message=f"Uso proibido da função dinâmica '{func_name}()'.",
                    suggestion="Remover o uso de eval/exec e substituir por parsing seguro ou despacho explícito.",
                )
            )

        # Checa chamadas a os.system ou subprocess(shell=True)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                self.issues.append(
                    Issue(
                        code="UNSAFE_OS_SYSTEM",
                        category="vulnerability",
                        severity="blocker",
                        file_path=self.file_path,
                        line_number=node.lineno,
                        message="Chamada insegura a 'os.system()'.",
                        suggestion="Utilizar subprocess.run com lista de argumentos sem shell=True.",
                    )
                )

        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # 4. Bug / Reliability: Bare except clause (except:)
        if node.type is None:
            self.issues.append(
                Issue(
                    code="BARE_EXCEPT_CLAUSE",
                    category="bug",
                    severity="major",
                    file_path=self.file_path,
                    line_number=node.lineno,
                    message="Cláusula 'except:' vazia captura todas as exceções indiscriminadamente.",
                    suggestion="Especificar o tipo exato da exceção esperada (ex: except ValueError:).",
                )
            )
        self.generic_visit(node)

    def _check_nesting(self, node: ast.AST) -> None:
        self._current_nesting += 1
        if self._current_nesting > 3:
            lineno = getattr(node, "lineno", None)
            self.issues.append(
                Issue(
                    code="COGNITIVE_COMPLEXITY",
                    category="code_smell",
                    severity="major",
                    file_path=self.file_path,
                    line_number=lineno,
                    message=f"Profundidade de aninhamento ({self._current_nesting}) excede o limite recomendado (3).",
                    suggestion="Simplificar fluxo com early returns ou extração de métodos.",
                )
            )
        self.generic_visit(node)
        self._current_nesting -= 1

    def visit_If(self, node: ast.If) -> None:
        self._check_nesting(node)

    def visit_For(self, node: ast.For) -> None:
        self._check_nesting(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_nesting(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._check_nesting(node)


def analyze_python_source(file_path: str, source_code: str) -> List[Issue]:
    """Executa a análise estática completa no estilo SonarQube para um arquivo."""
    issues: List[Issue] = []

    # 1. Checagem de Sintaxe (Bug Blocker)
    try:
        tree = ast.parse(source_code, filename=file_path)
    except SyntaxError as e:
        issues.append(
            Issue(
                code="SYNTAX_ERROR",
                category="bug",
                severity="blocker",
                file_path=file_path,
                line_number=e.lineno,
                message=f"Erro de sintaxe no código Python: {e.msg}",
                suggestion="Corrigir a sintaxe antes de submeter aos testes.",
            )
        )
        return issues

    # 2. Varredura de Segredos Hardcoded (Vulnerability Critical)
    for idx, line in enumerate(source_code.splitlines(), start=1):
        for pattern in SECRET_PATTERNS:
            if pattern.search(line):
                issues.append(
                    Issue(
                        code="HARDCODED_CREDENTIAL",
                        category="vulnerability",
                        severity="critical",
                        file_path=file_path,
                        line_number=idx,
                        message="Possível credencial, token ou chave de API identificada em texto plano.",
                        suggestion="Mover a credencial para variáveis de ambiente ou arquivo de configuração isolado.",
                    )
                )

    # 3. Varredura AST (Bugs, Insegurança, Code Smells e Complexidade)
    visitor = SonarQubeAstVisitor(file_path, source_code)
    visitor.visit(tree)
    issues.extend(visitor.issues)

    return issues


def validate_codebase_static(
    worktree_path: Path,
    target_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Executa a validação estática em todos os arquivos Python alterados ou no worktree inteiro."""
    base = worktree_path.resolve()
    all_issues: List[Issue] = []

    files_to_check: List[Path] = []
    ignored_dirs = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "site-packages"}

    if target_files is not None:
        if len(target_files) == 0:
            return ValidationResult(
                validator_name="static_code_analysis",
                status="pass",
                command_or_rule="sonarqube_ast_rules",
                exit_code=0,
                details="Nenhum arquivo Python alterado no diff para análise estática (NO_CHANGES).",
                requires_interrupt=False,
                issues=[],
            )
        for f in target_files:
            p = (base / f).resolve()
            if not p.exists() and f.startswith(f"{base.name}/"):
                p = (base / f[len(base.name) + 1:]).resolve()
            if not p.exists() and (base.parent / f).exists():
                p = (base.parent / f).resolve()
            if p.exists() and p.suffix == ".py" and not any(ignored in p.parts for ignored in ignored_dirs):
                files_to_check.append(p)
        if not files_to_check:
            return ValidationResult(
                validator_name="static_code_analysis",
                status="pass",
                command_or_rule="sonarqube_ast_rules",
                exit_code=0,
                details="Nenhum arquivo Python afetado pelo diff requer análise estática.",
                requires_interrupt=False,
                issues=[],
            )
    else:
        for p in base.glob("**/*.py"):
            if not any(ignored in p.parts for ignored in ignored_dirs):
                files_to_check.append(p)

    for py_file in files_to_check:
        try:
            rel_path = str(py_file.relative_to(base))
        except ValueError:
            rel_path = str(py_file)
        
        try:
            content = py_file.read_text(encoding="utf-8")
            file_issues = analyze_python_source(rel_path, content)
            all_issues.extend(file_issues)
        except Exception as e:
            all_issues.append(
                Issue(
                    code="FILE_READ_ERROR",
                    category="bug",
                    severity="major",
                    file_path=rel_path,
                    message=f"Não foi possível ler o arquivo para análise estática: {e}",
                )
            )

    # Avaliação dos Portões de Qualidade (Quality Gate)
    has_blockers = any(i.severity in ("blocker", "critical") for i in all_issues)
    has_hotspots = any(i.category == "security_hotspot" for i in all_issues)

    if has_blockers:
        status = "fail"
    else:
        status = "pass"

    details = (
        f"SonarQube Static Analysis concluída: {len(all_issues)} apontamento(s) encontrado(s). "
        f"Blockers/Critical: {sum(1 for i in all_issues if i.severity in ('blocker', 'critical'))} | "
        f"Major/Minor: {sum(1 for i in all_issues if i.severity in ('major', 'minor'))}."
    )

    return ValidationResult(
        validator_name="static_code_analysis",
        status=status,
        command_or_rule="sonarqube_ast_rules",
        exit_code=1 if has_blockers else 0,
        details=details,
        requires_interrupt=has_hotspots,
        issues=all_issues,
    )
