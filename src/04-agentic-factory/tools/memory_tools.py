"""Ferramentas de memória para o worker: anotação bruta (WAL) e portão sensível de commit."""

import datetime
import json
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool


def create_memory_tools(raw_memories_file: Path, memory_store_dir: Optional[Path] = None):
    """Cria as tools de anotação WAL e de gravação sensível."""
    raw_file = raw_memories_file.resolve()
    store_dir = (memory_store_dir or (raw_file.parent / "store")).resolve()

    @tool
    def record_raw_memory(concept: str, context: str, suggested_action: str) -> str:
        """Registra uma descoberta, heurística ou aprendizado da sessão em formato append-only (WAL).
        
        ATENÇÃO: Não registre código óbvio ou sintaxe básica que já esteja clara nos arquivos.
        Registre apenas regras de negócio, pegadinhas de protocolo ou preferências alinhadas.
        
        Args:
            concept: Conceito ou heurística central descoberta.
            context: O que gerou essa descoberta (ex: 'durante a validação de alcançabilidade de steps').
            suggested_action: Como agentes futuros devem agir ao se deparar com essa situação.
        """
        try:
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "concept": concept.strip(),
                "context": context.strip(),
                "suggested_action": suggested_action.strip(),
            }
            with raw_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return f"Sucesso: Descoberta registrada no WAL em '{raw_file.name}' para destilação futura."
        except Exception as e:
            return f"Erro ao registrar memória bruta: {e}"

    @tool
    def commit_memory(candidate_id: str, slug: str, content: str) -> str:
        """Grava uma memória destilada e validada definitivamente no repositório de memórias.
        
        Esta ferramenta é classificada como SENSÍVEL e requer aprovação humana prévia via interrupt_on.
        
        Args:
            candidate_id: Identificador da memória destilada proposta.
            slug: Nome curto para o arquivo da memória (ex: 'mcp-plan-reachability').
            content: Conteúdo estruturado em Markdown com frontmatter.
        """
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
            target = store_dir / f"{slug}.md"
            target.write_text(content, encoding="utf-8")
            return f"Sucesso: Memória '{slug}' gravada permanentemente após validação humana."
        except Exception as e:
            return f"Erro ao consolidar memória: {e}"

    return [record_raw_memory, commit_memory]
