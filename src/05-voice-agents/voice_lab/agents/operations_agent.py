"""Agente conversacional de operações do Graph Engineering Lab."""

import uuid
from typing import Any, Dict
from langchain_core.messages import AIMessage, HumanMessage
from voice_lab.contracts.state import ConversationState, ActionProposal, ToolResult
from voice_lab.graph.validators import evaluate_decision_intent
from voice_lab.tools.operational_tools import lookup_policy, list_jobs


def conversational_agent_node(state: ConversationState) -> Dict[str, Any]:
    """Processa o turno de entrada do usuário.
    Se houver proposta pendente, avalia a resposta; senão, detecta necessidade de leitura ou proposta."""
    messages = state.messages
    if not messages:
        return {"messages": [AIMessage(content="Olá! Sou o assistente de operações do Graph Engineering Lab. Como posso ajudar?")]}

    last_user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = str(m.content).strip()
            break

    # Se existe uma proposta pendente, avaliar confirmação/rejeição
    if state.pending_proposal and state.pending_proposal.status == "pending":
        intent, latency_ms = evaluate_decision_intent(last_user_msg, state.pending_proposal)
        
        if intent == "CONFIRM":
            state.pending_proposal.status = "confirmed"
            return {"pending_proposal": state.pending_proposal}
            
        elif intent == "REJECT":
            rejected_proposal = state.pending_proposal
            rejected_proposal.status = "rejected"
            response_text = f"Entendido. Ação '{rejected_proposal.summary_for_user}' foi cancelada sem efeitos colaterais."
            return {
                "messages": [AIMessage(content=response_text)],
                "pending_proposal": None,
                "last_tool_result": ToolResult(
                    proposal_id=rejected_proposal.proposal_id,
                    tool_name=rejected_proposal.tool_name,
                    status="failure",
                    error="Cancelado pelo usuário"
                )
            }
        elif intent == "MODIFY":
            state.pending_proposal.status = "rejected"
            response_text = "Entendido que deseja modificar a solicitação. Por favor, especifique os novos parâmetros."
            return {
                "messages": [AIMessage(content=response_text)],
                "pending_proposal": None
            }
        else:
            response_text = f"Tenho uma proposta pendente: {state.pending_proposal.summary_for_user}. Você confirma a execução ou prefere cancelar?"
            return {"messages": [AIMessage(content=response_text)]}

    # Intenção de Disparar Experimento (Ação Mutante)
    u_lower = last_user_msg.lower()
    if any(k in u_lower for k in ["dispara", "rodar", "rode", "executar", "executa", "iniciar", "teste"]) and "experimento" in u_lower:
        exp_id = "05_voice_agents"
        for i in ["01", "02", "03", "04", "05"]:
            if i in u_lower:
                exp_id = f"{i}_experiment" if i != "05" else "05_voice_agents"
                break
        
        profile = "local_light"
        if "hybrid" in u_lower or "hibrido" in u_lower:
            profile = "hybrid_control"
        elif "preset" in u_lower or "hf" in u_lower:
            profile = "local_hf_preset"

        proposal = ActionProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:6]}",
            tool_name="trigger_experiment",
            arguments={"experiment_id": exp_id, "profile": profile},
            summary_for_user=f"Disparar o experimento '{exp_id}' sob o perfil '{profile}'",
            status="pending"
        )
        return {"pending_proposal": proposal}

    # Consulta de Status / Listagem de Jobs (Leitura)
    if any(k in u_lower for k in ["jobs", "experimentos", "status", "listar", "andamento"]):
        status_filter = "active" if "ativo" in u_lower else ("completed" if "concluido" in u_lower or "concluído" in u_lower else None)
        jobs_result = list_jobs.invoke({"status_filter": status_filter})
        jobs_summary = ", ".join([f"{j['job_id']} ({j['experiment']}: {j['status']})" for j in jobs_result["jobs"]])
        return {
            "messages": [AIMessage(content=f"Encontrei {jobs_result['total']} experimentos registrados: {jobs_summary}.")],
            "last_tool_result": ToolResult(tool_name="list_jobs", status="success", data=jobs_result)
        }

    # Consulta de Políticas e Regras (Leitura)
    if any(k in u_lower for k in ["regra", "política", "politica", "o que é", "significa", "barge", "confirmacao", "s2s", "cascata"]):
        topic = "barge_in" if "barge" in u_lower else ("s2s" if "s2s" in u_lower else ("cascata" if "cascata" in u_lower else "confirmacao"))
        policy_res = lookup_policy.invoke({"topic": topic})
        text = f"Segundo a política de {policy_res['topic']} do laboratório: {policy_res['policy']}" if policy_res["found"] else f"Definição não encontrada para '{topic}'."
        return {
            "messages": [AIMessage(content=text)],
            "last_tool_result": ToolResult(tool_name="lookup_policy", status="success", data=policy_res)
        }

    return {
        "messages": [AIMessage(content="Posso ajudar você a consultar políticas, listar o status de experimentos ou disparar um novo job com confirmação. O que deseja fazer?")]
    }
