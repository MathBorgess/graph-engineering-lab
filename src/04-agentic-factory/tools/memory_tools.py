"""Ferramentas de memória para o worker: WAL estruturado anti-duplicação e commit sensível."""

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool


def create_memory_tools(
    raw_memories_file: Path,
    memory_store_dir: Optional[Path] = None,
    worktree_path: Optional[Path] = None,
    enforce_strict_dedup: bool = True,
):
    """Cria as tools de anotação WAL e de gravação sensível.
    
    Args:
        raw_memories_file: Arquivo .jsonl de append-only para registro de descobertas.
        memory_store_dir: Diretório para memória destilada permanente.
        worktree_path: Caminho do worktree para validar resolução de evidências.
        enforce_strict_dedup: Se True (Braço B), a tool recusa duplicatas e valida evidência;
                              se False (Braço A), aceita como a tool legada.
    """
    raw_file = raw_memories_file.resolve()
    store_dir = (memory_store_dir or (raw_file.parent / "store")).resolve()
    base_wt = worktree_path.resolve() if worktree_path else None

    @tool
    def record_raw_memory(
        concept_id: str,
        claim: str,
        evidence: str,
        supersedes: Optional[str] = None,
    ) -> str:
        """Registra uma descoberta, heurística ou aprendizado da sessão em formato append-only (WAL).
        
        Args:
            concept_id: Identificador único em formato slug (ex: 'preflight-reachability-linear').
            claim: Afirmação técnica precisa ou heurística de negócio aprendida.
            evidence: Referência verificável 'arquivo:linha' (ex: 'laya_computer/preflight.py:37') ou ID de teste.
            supersedes: (Opcional) concept_id pré-existente que esta descoberta invalida ou substitui.
        """
        try:
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            entries = []
            if raw_file.exists():
                for line in raw_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass

            cid = concept_id.strip()
            
            # 1. Checagem Anti-Duplicação estrita (Braço B)
            if enforce_strict_dedup:
                existing_active = next(
                    (e for e in entries if (e.get("concept_id") == cid or e.get("concept") == cid) and e.get("status", "active") == "active"),
                    None
                )
                if existing_active:
                    if supersedes != cid and not supersedes:
                        existing_claim = existing_active.get("claim") or existing_active.get("context") or ""
                        return (
                            f"DUPLICATE_CONCEPT_REJECTED: O conceito '{cid}' já está registrado no WAL "
                            f"(claim existente: '{existing_claim[:80]}'). "
                            f"Se você pretende atualizar ou invalidar esta heurística, use supersedes='{cid}'."
                        )

                # 2. Resolução estrita de evidência (arquivo e linha devem existir)
                if base_wt and cid != "no_new_concepts":
                    ev = evidence.strip()
                    if ":" in ev and "::" not in ev:
                        parts = ev.split(":")
                        rel_file = parts[0].strip()
                        line_str = parts[1].strip()
                        target_file = base_wt / rel_file
                        if not target_file.exists() and rel_file.startswith(f"{base_wt.name}/"):
                            target_file = base_wt / rel_file[len(base_wt.name) + 1:]
                        if not target_file.exists():
                            return f"EVIDENCE_RESOLUTION_FAILED: O arquivo '{rel_file}' citado na evidência não existe no repositório."
                        
                        try:
                            line_num = int(line_str)
                            total_lines = len(target_file.read_text(encoding="utf-8").splitlines())
                            if line_num < 1 or line_num > total_lines:
                                return f"EVIDENCE_RESOLUTION_FAILED: A linha {line_num} não existe em '{rel_file}' (o arquivo possui {total_lines} linhas)."
                        except ValueError:
                            return f"EVIDENCE_RESOLUTION_FAILED: Número de linha inválido '{line_str}' na evidência."
                    elif "::" in ev:
                        test_file_str = ev.split("::")[0].strip()
                        target_file = base_wt / test_file_str
                        if not target_file.exists():
                            return f"EVIDENCE_RESOLUTION_FAILED: Arquivo de teste '{test_file_str}' não existe."
                    else:
                        return f"EVIDENCE_RESOLUTION_FAILED: Formato de evidência inválido ('{ev}'). Use 'caminho:linha' ou 'teste.py::func'."

            # Atualiza status se supersedes foi fornecido
            if supersedes:
                new_entries = []
                for e in entries:
                    if e.get("concept_id") == supersedes or e.get("concept") == supersedes:
                        e["status"] = "superseded"
                    new_entries.append(e)
                raw_file.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in new_entries) + "\n", encoding="utf-8")

            entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "concept_id": cid,
                "claim": claim.strip(),
                "evidence": evidence.strip(),
                "supersedes": supersedes.strip() if supersedes else None,
                "status": "active",
            }
            with raw_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return f"Sucesso: Descoberta '{cid}' registrada no WAL em '{raw_file.name}'."
        except Exception as e:
            return f"Erro ao registrar memória bruta: {e}"

    @tool
    def commit_memory(candidate_id: str, slug: str, content: str) -> str:
        """Grava uma memória destilada definitivamente no repositório de memórias (Requer aprovação HITL)."""
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
            target = store_dir / f"{slug}.md"
            target.write_text(content, encoding="utf-8")
            return f"Sucesso: Memória '{slug}' gravada permanentemente."
        except Exception as e:
            return f"Erro ao consolidar memória: {e}"

    return [record_raw_memory, commit_memory]
