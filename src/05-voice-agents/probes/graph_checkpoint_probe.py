"""Probe do Bloco 2: Validação de Two-Phase Commit, LangGraph Checkpoint e Resiliência a Quedas."""

import os
import sys
from pathlib import Path
from langchain_core.messages import HumanMessage
import mlflow

# Garantir que voice_lab esteja no PYTHONPATH
current_dir = Path(__file__).resolve().parent
package_root = current_dir.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from voice_lab.config import settings
from voice_lab.graph.checkpoints import get_checkpointer
from voice_lab.graph.builder import build_voice_graph


def run_graph_probe():
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    settings.ensure_directories()
    
    mlflow.set_tracking_uri(settings.get_mlflow_uri())
    mlflow.set_experiment(settings.mlflow_experiment_name)
    
    thread_id = "voice_session_probe_001"
    config = {"configurable": {"thread_id": thread_id}}
    
    print("\n========================================================")
    print("🧩 BLOCO 2 — PROBE DE GRAFO, TWO-PHASE COMMIT E CHECKPOINT")
    print("========================================================")
    print(f"Thread ID da Sessão: {thread_id}")
    print(f"Checkpointer SQLite: {settings.checkpoints_db}\n")

    with mlflow.start_run(run_name="probe_bloco_2_graph_resilience"):
        mlflow.log_params({
            "thread_id": thread_id,
            "checkpoints_db": str(settings.checkpoints_db),
        })

        # -------------------------------------------------------------
        # TURNO 1: Consulta de Leitura (Policy)
        # -------------------------------------------------------------
        print("--- [TURNO 1: Consulta de Política] ---")
        with get_checkpointer() as checkpointer:
            graph = build_voice_graph(checkpointer=checkpointer)
            input_state = {"messages": [HumanMessage(content="O que é barge-in no laboratório?")]}
            state_out = graph.invoke(input_state, config=config)
            
            reply_1 = state_out["messages"][-1].content
            print(f"Usuário: O que é barge-in no laboratório?")
            print(f"Agente: {reply_1}\n")
            assert "barge_in" in str(state_out.get("last_tool_result")), "Falha na tool de política"

        # -------------------------------------------------------------
        # TURNO 2: Intenção de Ação Mutante -> Geração de ActionProposal
        # -------------------------------------------------------------
        print("--- [TURNO 2: Pedido de Disparo de Experimento] ---")
        with get_checkpointer() as checkpointer:
            graph = build_voice_graph(checkpointer=checkpointer)
            input_state = {"messages": [HumanMessage(content="Por favor, rode o experimento 05 com o perfil hybrid")]}
            state_out = graph.invoke(input_state, config=config)
            
            reply_2 = state_out["messages"][-1].content
            proposal = state_out.get("pending_proposal")
            
            print(f"Usuário: Por favor, rode o experimento 05 com o perfil hybrid")
            print(f"Agente: {reply_2}")
            print(f"Estado pendente: {proposal}\n")
            
            assert proposal is not None, "Proposta pendente deveria ter sido criada!"
            assert proposal.status == "pending", "Status da proposta deve ser 'pending'"
            assert proposal.arguments["experiment_id"] == "05_voice_agents"
            assert proposal.arguments["profile"] == "hybrid_control"

        # -------------------------------------------------------------
        # TURNO 3: SIMULAÇÃO DE QUEDA DE SESSÃO / CRASH
        # Destruímos a instância em memória. O próximo invoke deve ler do SQLite.
        # -------------------------------------------------------------
        print("💥 [SIMULAÇÃO DE CRASH / QUEDA DE CONEXÃO WEBRTC] 💥")
        print("Processo em memória reiniciado. Restaurando sessão a partir do SQLite...")
        
        with get_checkpointer() as checkpointer:
            recovered_graph = build_voice_graph(checkpointer=checkpointer)
            
            # Verificar se o estado persistido no SQLite possui a proposta ativa
            checkpoint_state = recovered_graph.get_state(config)
            recovered_proposal = checkpoint_state.values.get("pending_proposal")
            print(f"Proposta recuperada do SQLite: {recovered_proposal.summary_for_user} (ID: {recovered_proposal.proposal_id})\n")
            assert recovered_proposal is not None, "Falha ao recuperar proposta pendente do SQLite após crash!"

            # Usuário reconectado confirma verbalmente a ação
            print("--- [TURNO 3: Confirmação verbal pós-recuperação] ---")
            input_state = {"messages": [HumanMessage(content="Sim, confirmo a execução!")]}
            state_out = recovered_graph.invoke(input_state, config=config)
            
            reply_3 = state_out["messages"][-1].content
            print(f"Usuário: Sim, confirmo a execução!")
            print(f"Agente: {reply_3}\n")
            
            assert state_out.get("pending_proposal") is None, "Proposta pendente deve ter sido consumida!"
            last_res = state_out.get("last_tool_result")
            assert last_res is not None and last_res.status == "success", "Ação deveria ter sido executada com sucesso!"
            print(f"Resultado operacional: {last_res.data}\n")

        # -------------------------------------------------------------
        # TURNO 4: Rejeição determinística
        # -------------------------------------------------------------
        print("--- [TURNO 4: Nova proposta e Rejeição Verbal] ---")
        with get_checkpointer() as checkpointer:
            graph = build_voice_graph(checkpointer=checkpointer)
            
            # Pedir ação
            graph.invoke({"messages": [HumanMessage(content="Dispara o experimento 01")]}, config=config)
            # Rejeitar
            state_out = graph.invoke({"messages": [HumanMessage(content="Não, espera, cancela!")]}, config=config)
            reply_4 = state_out["messages"][-1].content
            
            print(f"Usuário: Dispara o experimento 01 -> Não, espera, cancela!")
            print(f"Agente: {reply_4}")
            assert state_out.get("pending_proposal") is None, "Proposta rejeitada deve ser limpa!"
            assert state_out.get("last_tool_result").status == "failure", "Resultado deve constar como cancelado/rejeitado"

        mlflow.log_metrics({
            "turns_completed": 4,
            "session_crashes_recovered": 1,
            "mutations_confirmed": 1,
            "mutations_rejected": 1,
        })
        
        print("\n========================================================")
        print("✅ PROBE DO BLOCO 2 CONCLUÍDO COM SUCESSO!")
        print("Resiliência de sessão, Checkpoint SQLite e Two-Phase Commit 100% validados.")
        print("========================================================\n")


if __name__ == "__main__":
    run_graph_probe()
