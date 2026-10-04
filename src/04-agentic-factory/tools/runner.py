"""Ferramenta de execução de testes parametrizada e confinada ao worktree."""

import subprocess
import sys
from pathlib import Path
from langchain_core.tools import tool


def create_test_runner_tool(worktree_path: Path):
    """Cria uma tool run_pytest com execução controlada dentro do worktree."""
    worktree = worktree_path.resolve()

    @tool
    def run_pytest(test_path: str = "") -> str:
        """Executa a suíte de testes pytest no repositório de trabalho e retorna os resultados.
        
        Args:
            test_path: Caminho específico de teste (ex: 'tests/test_preflight.py') ou vazio para todos.
        """
        import shutil
        worktree_pytest = worktree / ".venv" / "bin" / "pytest"
        if worktree_pytest.exists():
            cmd = [str(worktree_pytest), "-q"]
        elif shutil.which("uv") and (worktree / "pyproject.toml").exists():
            cmd = ["uv", "run", "pytest", "-q"]
        else:
            cmd = [sys.executable, "-m", "pytest", "-q"]
        if test_path.strip():
            # Assegura que o caminho não tente escapar
            clean_path = test_path.strip().lstrip("/")
            if ".." in clean_path:
                return "Erro: Caminho de teste inválido."
            cmd.append(clean_path)

        try:
            result = subprocess.run(
                cmd,
                cwd=str(worktree),
                capture_output=True,
                text=True,
                timeout=120,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            status = "PASSOU" if result.returncode == 0 else f"FALHOU (exit code {result.returncode})"
            
            output = [f"=== Resultado dos Testes: {status} ==="]
            if stdout:
                output.append(f"STDOUT:\n{stdout}")
            if stderr:
                output.append(f"STDERR:\n{stderr}")
            return "\n\n".join(output)
        except subprocess.TimeoutExpired:
            return "Erro: A execução dos testes excedeu o tempo limite de 120s."
        except Exception as e:
            return f"Erro ao executar pytest: {e}"

    return run_pytest
