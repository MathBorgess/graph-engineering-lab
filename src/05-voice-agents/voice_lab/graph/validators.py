"""Validadores determinísticos, Guardrails e Execução SAGA para o grafo de voz."""

import time
from typing import Any, Dict, Literal
from langchain_core.messages import AIMessage
from voice_lab.contracts.state import ConversationState, ActionProposal, ToolResult
from voice_lab.tools.operational_tools import execute_trigger_experiment


DecisionIntent = Literal["CONFIRM", "REJECT", "MODIFY", "AMBIGUOUS"]


def evaluate_decision_intent(user_utterance: str, pending_proposal: ActionProposal) -> tuple[DecisionIntent, float]:
    """Avalia a intenção do usuário frente a uma proposta pendente."""
    t0 = time.perf_counter()
    u = user_utterance.lower().strip()
    
    confirm_phrases = [
        "sim", "confirma", "pode", "executa", "positivo", "claro", 
        "confirmo", "ok", "manda ver", "bora", "com certeza", "autorizo"
    ]
    reject_phrases = [
        "não", "nao", "cancela", "esquece", "espera", "para", 
        "não quero", "cancelo", "aborta", "desiste"
    ]
    modify_phrases = ["muda", "troca", "em vez de", "altera", "outro perfil", "outro experimento"]
    
    intent: DecisionIntent = "AMBIGUOUS"
    if any(p in u for p in modify_phrases):
        intent = "MODIFY"
    elif any(p in u for p in reject_phrases):
        intent = "REJECT"
    elif any(p in u for p in confirm_phrases):
        intent = "CONFIRM"
        
    decision_latency_ms = (time.perf_counter() - t0) * 1000.0
    return intent, decision_latency_ms


def guardrail_validator_node(state: ConversationState) -> Dict[str, Any]:
    """GUARDRAIL ARQUITETURAL: Intercepta qualquer tentativa de ação mutante.
    NÃO confia no system prompt do LLM.
    Se a proposta não tiver status=='confirmed', a execução é bloqueada e
    o agente é forçado a emitir o pedido de confirmação com os parâmetros fixados."""
    proposal = state.pending_proposal
    if not proposal:
        return {}

    if proposal.status == "pending":
        prompt_confirm = (
            f"Você solicitou: {proposal.summary_for_user}. "
            f"Posso confirmar a execução desta ação?"
        )
        return {"messages": [AIMessage(content=prompt_confirm)]}

    return {}


def saga_executor_node(state: ConversationState) -> Dict[str, Any]:
    """Executa a transação mutante e gerencia o padrão SAGA em caso de erro."""
    proposal = state.pending_proposal
    if not proposal or proposal.status != "confirmed":
        return {}

    try:
        tool_result = execute_trigger_experiment(**proposal.arguments)
        proposal.status = "executed"
        
        reply = (
            f"Confirmado! Ação executada com sucesso. "
            f"Job ID gerado: {tool_result.data.get('job_id')} para o experimento '{tool_result.data.get('experiment')}'."
        )
        return {
            "messages": [AIMessage(content=reply)],
            "pending_proposal": None,
            "last_tool_result": tool_result
        }
    except Exception as e:
        proposal.status = "failed"
        error_result = ToolResult(
            proposal_id=proposal.proposal_id,
            tool_name=proposal.tool_name,
            status="unknown",
            error=str(e),
            retryable=True
        )
        return {
            "messages": [AIMessage(content=f"Aviso operacional: A execução de '{proposal.tool_name}' falhou: {str(e)}.")],
            "pending_proposal": None,
            "last_tool_result": error_result
        }
