"""Montagem do StateGraph da fábrica agêntica com LangGraph e portões HITL."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

try:
    from ..contracts.state import FactoryState
    from .nodes import worker_node, validator_node, judge_node, dod_node, memory_distillation_node
    from .gates import scope_review_gate, final_acceptance_gate
    from ..agents.worker import create_factory_worker
except (ImportError, ValueError):
    from contracts.state import FactoryState
    from graph.nodes import worker_node, validator_node, judge_node, dod_node, memory_distillation_node
    from graph.gates import scope_review_gate, final_acceptance_gate
    from agents.worker import create_factory_worker


def build_agentic_factory_graph(
    worktree_path: Path,
    raw_memories_file: Path,
    allowed_scope_patterns: Optional[List[str]] = None,
    max_worker_attempts: int = 3,
    model_id: str = "gpt-6-luna",
    provider: str = "codex",
    checkpointer: Optional[BaseCheckpointSaver] = None,
    base_url: Optional[str] = None,
):
    """Constrói e compila o StateGraph completo da fábrica de software agêntica."""
    scope_patterns = allowed_scope_patterns or ["laya_computer/*", "server.py", "tests/*", "README.md"]
    checkpointer_instance = checkpointer if checkpointer is not None else InMemorySaver()

    # 1. Cria a instância do Worker
    worker_inst, skills_registry = create_factory_worker(
        worktree_path=worktree_path,
        raw_memories_file=raw_memories_file,
        model_id=model_id,
        provider=provider,
        base_url=base_url,
    )

    # 2. Definição do StateGraph
    builder = StateGraph(FactoryState)

    # 3. Adiciona os Nós
    async def _worker_step(state):
        return await worker_node(state, worker_inst)

    def _validator_step(state):
        return validator_node(state, scope_patterns)

    async def _judge_step(state):
        return await judge_node(state, base_url=base_url)

    builder.add_node("worker", _worker_step)
    builder.add_node("validators", _validator_step)
    builder.add_node("scope_gate", scope_review_gate)
    builder.add_node("judge", _judge_step)
    builder.add_node("dod", dod_node)
    builder.add_node("final_gate", final_acceptance_gate)
    builder.add_node("memory_distillation", memory_distillation_node)

    # 4. Roteamento e Arestas
    builder.add_edge(START, "worker")
    builder.add_edge("worker", "validators")

    # Aresta condicional após os validators
    def route_after_validators(state: Dict[str, Any]) -> str:
        results = state.get("validation_results", [])
        scope_res = next((r for r in results if r.validator_name == "scope_validator"), None)
        
        # 1. Se houver desvio de escopo, para no scope_gate
        if scope_res and scope_res.requires_interrupt:
            return "scope_gate"

        # 2. Se falhar em testes ou regras blocker
        if not state.get("is_valid", False):
            if state.get("worker_attempt", 0) < max_worker_attempts:
                return "worker"  # Loop de reparo
            return END  # Orçamento esgotado

        # 3. Se passou em tudo, avança para o DeepAgent Judge
        return "judge"

    builder.add_conditional_edges("validators", route_after_validators)

    # Aresta condicional após o scope_gate
    def route_after_scope_gate(state: Dict[str, Any]) -> str:
        decisions = state.get("human_decisions", [])
        last_decision = decisions[-1] if decisions else {}
        action = last_decision.get("action_type")
        if action == "approve_and_continue":
            return "judge"
        return "worker"  # Reverter/retroceder

    builder.add_conditional_edges("scope_gate", route_after_scope_gate)

    # Aresta condicional após o judge
    def route_after_judge(state: Dict[str, Any]) -> str:
        if not state.get("judge_ready_for_dod", True):
            # Judge solicitou reparo de blocker dentro do orçamento
            if state.get("worker_attempt", 0) < max_worker_attempts:
                return "worker"
            return END
        return "dod"

    builder.add_conditional_edges("judge", route_after_judge)

    # Aresta condicional após o cálculo da DoD
    def route_after_dod(state: Dict[str, Any]) -> str:
        if state.get("ready_for_human_acceptance", False):
            return "final_gate"
        if state.get("worker_attempt", 0) < max_worker_attempts:
            return "worker"
        return END

    builder.add_conditional_edges("dod", route_after_dod)

    # Aresta condicional após o aceite final
    def route_after_final_gate(state: Dict[str, Any]) -> str:
        status = state.get("final_status")
        if status == "completed":
            return "memory_distillation"
        if status == "in_progress":
            # Humano pediu mudanças
            return "worker"
        return END

    builder.add_conditional_edges("final_gate", route_after_final_gate)
    builder.add_edge("memory_distillation", END)

    # 5. Compila com Checkpointer
    return builder.compile(checkpointer=checkpointer_instance)
