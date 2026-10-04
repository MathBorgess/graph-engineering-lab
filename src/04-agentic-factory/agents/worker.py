"""Factory para instanciação do Worker Deep Agent da fábrica de software agêntica."""

from pathlib import Path
from typing import Optional
from deepagents import create_deep_agent
from proxy.client import create_model
try:
    from ..skills.registry import DeferredSkillsRegistry
    from ..tools.sandbox_fs import create_sandbox_fs_tools
    from ..tools.runner import create_test_runner_tool
    from ..tools.memory_tools import create_memory_tools
except (ImportError, ValueError):
    from skills.registry import DeferredSkillsRegistry
    from tools.sandbox_fs import create_sandbox_fs_tools
    from tools.runner import create_test_runner_tool
    from tools.memory_tools import create_memory_tools


def create_factory_worker(
    worktree_path: Path,
    raw_memories_file: Path,
    model_id: str = "gpt-6-luna",
    provider: str = "codex",
    checkpointer=None,
    base_url: Optional[str] = None,
):
    """Instancia o worker Deep Agent com ferramentas de sandbox e portão de interrupção HITL.
    
    Args:
        worktree_path: Diretório isolado onde o código é lido e editado.
        raw_memories_file: Arquivo .jsonl de append-only para registro de descobertas intermediárias.
        model_id: Identificador do modelo no proxy (padrão 'gpt-6-luna').
        provider: Provedor no proxy ('codex' ou 'claude').
        checkpointer: Instância do Checkpointer do LangGraph (ex: InMemorySaver).
        base_url: URL base opcional do proxy.
    """
    # 1. Conexão com o modelo
    model = create_model(provider, model_id, base_url=base_url)
    
    # 2. Catálogo de Deferred Skills
    skills_registry = DeferredSkillsRegistry()
    
    # 3. Montagem do conjunto de ferramentas do Worker
    fs_tools = create_sandbox_fs_tools(worktree_path)
    runner_tool = create_test_runner_tool(worktree_path)
    mem_tools = create_memory_tools(raw_memories_file)
    load_skill_tool = skills_registry.build_tool()
    
    tools = [*fs_tools, runner_tool, load_skill_tool, *mem_tools]
    
    # 4. System prompt com catálogo compacto (máximo 110 caracteres)
    compact_catalog = skills_registry.get_compact_catalog_prompt(max_desc_len=110)
    
    system_prompt = f"""You are the Deep Agent implementation worker of the Agentic Software Factory.
You are strictly confined to the isolated worktree directory: {worktree_path}.
You cannot write to or modify files outside of this worktree.

{compact_catalog}

Operational Rules:
1. Always load relevant domain skills using `load_skill(name)` before designing or modifying protocol files.
2. Note concepts, edge cases, and human-aligned heuristics using `record_raw_memory`. Do NOT record obvious syntax or code lines already clearly expressed in the codebase.
3. Test your implementations with `run_pytest` before declaring your work ready for validators.
4. Permanent memory consolidation (`commit_memory`) is sensitive and requires explicit human approval.
"""

    # 5. Instanciação com DeepAgents
    worker = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        interrupt_on={"commit_memory": True},
        checkpointer=checkpointer,
    )
    
    return worker, skills_registry
