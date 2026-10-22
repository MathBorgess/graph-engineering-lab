"""Validadores determinísticos, Guardrails e Execução SAGA para o grafo de voz."""

import time
import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Literal
from langchain_core.messages import AIMessage
from voice_lab.contracts.state import ConversationState, ActionProposal, ToolResult
from voice_lab.tools.operational_tools import execute_trigger_experiment


DecisionIntent = Literal["CONFIRM", "REJECT", "MODIFY", "AMBIGUOUS"]


def evaluate_decision_intent(user_utterance: str, pending_proposal: ActionProposal) -> tuple[DecisionIntent, float]:
    """Avalia a intenção do usuário frente a uma proposta pendente."""
    t0 = time.perf_counter()
    # Restrict acceptance to an entire explicit response, never a substring.
    text = "".join(c for c in unicodedata.normalize("NFKD", user_utterance.casefold())
                   if not unicodedata.combining(c))
    u = " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())
    confirmations = {
        "sim", "confirmo", "sim confirmo", "confirmo a execucao",
        "sim confirmo a execucao", "autorizo", "autorizo a execucao",
        "pode executar", "pode executar a acao",
    }
    intent: DecisionIntent = "AMBIGUOUS"
    if re.search(r"\b(nao|cancela|cancele|cancelo|aborta|aborte|espera|espere|pare)\b", u):
        intent = "REJECT"
    elif re.search(r"\b(muda|mude|troca|troque|altera|altere)\b|em vez de|outro perfil|outro experimento", u):
        intent = "MODIFY"
    elif "?" not in user_utterance and u in confirmations:
        intent = "CONFIRM"

    decision_latency_ms = (time.perf_counter() - t0) * 1000.0
    return intent, decision_latency_ms


def proposal_digest(proposal: ActionProposal) -> str:
    """Bind consent and retry identity to the exact proposal/version/arguments."""
    payload = {"proposal_id": proposal.proposal_id, "version": proposal.version,
               "tool_name": proposal.tool_name, "arguments": proposal.arguments}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


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
        if proposal.tool_name != "trigger_experiment":
            raise ValueError("Ferramenta não autorizada pelo despachante")
        digest = proposal_digest(proposal)
        if not proposal.confirmed_by_message_id or proposal.confirmation_digest != digest:
            raise ValueError("Confirmação ausente ou parâmetros alterados após a confirmação")
        tool_result = execute_trigger_experiment(
            **proposal.arguments, idempotency_key=f"voice-action:{digest}")
        tool_result.proposal_id = proposal.proposal_id
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
