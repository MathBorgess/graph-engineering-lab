"""Ferramentas de sistema de arquivos estritamente confinadas ao worktree."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from langchain_core.tools import tool


def _resolve_safe_path(worktree_path: Path, relative_or_abs_path: str) -> Path:
    """Resolve o caminho garantindo que ele não escape do worktree isolado."""
    base = worktree_path.resolve()
    target = (base / relative_or_abs_path).resolve()
    if not str(target).startswith(str(base)):
        raise PermissionError(f"Acesso negado: o caminho '{relative_or_abs_path}' escapa do sandbox {base}.")
    return target


def create_sandbox_fs_tools(
    worktree_path: Path,
    readonly_files: Optional[Set[str]] = None,
    write_attempts_log: Optional[List[dict]] = None,
) -> list:
    """Cria instâncias de ferramentas de filesystem presas ao worktree_path fornecido."""
    worktree = worktree_path.resolve()
    readonly_set = {str(Path(f).as_posix()).lstrip("/") for f in (readonly_files or set())}

    def _is_readonly(path_str: str) -> bool:
        norm = str(Path(path_str).as_posix()).lstrip("/")
        return norm in readonly_set or any(norm == ro or norm.endswith("/" + ro) for ro in readonly_set)

    @tool
    def read_file(path: str) -> str:
        """Lê o conteúdo completo de um arquivo de texto dentro do repositório/worktree.
        
        Args:
            path: Caminho relativo do arquivo em relação à raiz do worktree.
        """
        try:
            target = _resolve_safe_path(worktree, path)
            if not target.exists():
                return f"Erro: Arquivo '{path}' não encontrado."
            if not target.is_file():
                return f"Erro: '{path}' é um diretório, não um arquivo."
            return target.read_text(encoding="utf-8")
        except Exception as e:
            return f"Erro ao ler arquivo: {e}"

    @tool
    def edit_file(path: str, old_content: str, new_content: str) -> str:
        """Substitui um bloco exato de texto dentro de um arquivo existente.
        
        Args:
            path: Caminho relativo do arquivo em relação à raiz do worktree.
            old_content: Texto exato atualmente presente no arquivo a ser substituído.
            new_content: Novo texto que substituirá old_content.
        """
        try:
            if _is_readonly(path):
                if write_attempts_log is not None:
                    write_attempts_log.append({
                        "event": "PERMISSION_DENIED_READONLY_TEST",
                        "tool": "edit_file",
                        "path": path,
                    })
                return f"Erro: PERMISSION_DENIED_READONLY_TEST. Arquivo '{path}' é de teste pré-existente e somente-leitura. Crie novos arquivos de teste."
            target = _resolve_safe_path(worktree, path)
            if not target.exists():
                return f"Erro: Arquivo '{path}' não existe."
            current = target.read_text(encoding="utf-8")
            if old_content not in current:
                return f"Erro: 'old_content' não foi encontrado de forma exata dentro de '{path}'."
            updated = current.replace(old_content, new_content, 1)
            target.write_text(updated, encoding="utf-8")
            return f"Sucesso: Arquivo '{path}' atualizado."
        except Exception as e:
            return f"Erro ao editar arquivo: {e}"

    @tool
    def write_file(path: str, content: str) -> str:
        """Cria ou sobrescreve completamente um arquivo dentro do worktree.
        
        Args:
            path: Caminho relativo do arquivo em relação à raiz do worktree.
            content: Conteúdo de texto a ser gravado.
        """
        try:
            if _is_readonly(path):
                if write_attempts_log is not None:
                    write_attempts_log.append({
                        "event": "PERMISSION_DENIED_READONLY_TEST",
                        "tool": "write_file",
                        "path": path,
                    })
                return f"Erro: PERMISSION_DENIED_READONLY_TEST. Arquivo '{path}' é de teste pré-existente e somente-leitura. Crie novos arquivos de teste."
            target = _resolve_safe_path(worktree, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Sucesso: Arquivo '{path}' gravado."
        except Exception as e:
            return f"Erro ao gravar arquivo: {e}"

    @tool
    def list_dir(path: str = ".") -> str:
        """Lista os arquivos e subdiretórios presentes em uma pasta dentro do worktree.
        
        Args:
            path: Caminho relativo da pasta (padrão é a raiz do worktree).
        """
        try:
            target = _resolve_safe_path(worktree, path)
            if not target.exists():
                return f"Erro: Diretório '{path}' não encontrado."
            items = []
            for item in sorted(target.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                items.append(f"{prefix} {item.name}")
            return "\n".join(items) if items else "(diretório vazio)"
        except Exception as e:
            return f"Erro ao listar diretório: {e}"

    return [read_file, edit_file, write_file, list_dir]
