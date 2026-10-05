"""Montagem e compilação do StateGraph do agente de voz com LangGraph."""

from typing import Literal
from langgraph.graph import StateGraph, START, END
from voice_lab.contracts.state import ConversationState
from voice_lab.agents.operations_agent import conversational_agent_node
from voice_lab.graph.validators import guardrail_validator_node, saga_executor_node


def route_after_guardrail(state: ConversationState) -> Literal["saga_executor", "__end__"]:
    proposal = state.pending_proposal
    if proposal and proposal.status == "confirmed":
        return "saga_executor"
    return "__end__"


def build_voice_graph(checkpointer=None):
    """Constrói e compila o grafo com nó de agente, Guardrail determinístico e SAGA Executor."""
    builder = StateGraph(ConversationState)
    
    builder.add_node("agent", conversational_agent_node)
    builder.add_node("guardrail", guardrail_validator_node)
    builder.add_node("saga_executor", saga_executor_node)
    
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "guardrail")
    
    builder.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {
            "saga_executor": "saga_executor",
            "__end__": END
        }
    )
    builder.add_edge("saga_executor", END)
    
    return builder.compile(checkpointer=checkpointer)
