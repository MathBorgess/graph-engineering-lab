"""Probe do Bloco 4: Validação de Sandbox SQLite, Idempotência, SAGA e Streaming Antecipado."""

import os
import sys
import time
import asyncio
from pathlib import Path
import mlflow

# Garantir que voice_lab esteja no PYTHONPATH
current_dir = Path(__file__).resolve().parent
package_root = current_dir.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from voice_lab.config import settings
from voice_lab.tools.sandbox import sandbox
from voice_lab.tools.operational_tools import execute_trigger_experiment, execute_cancel_experiment, list_jobs
from voice_lab.audio.stream import TextSentenceChunker, BargeInController
from voice_lab.audio.codex_stream import stream_and_chunk_response
from voice_lab.contracts.events import TextChunkEvent


async def mock_codex_token_generator():
    """Simula um stream SSE de resposta vindo do proxy do Codex."""
    stream_chunks = [
        "Com ", "certeza! ",
        "Disparei ", "o ", "experimento ", "05 ", "com ", "perfil ", "local_light. ",
        "O ", "identificador ", "da ", "execução ", "é ", "job_run_54321. ",
        "Você ", "pode ", "acompanhar ", "os ", "traces ", "no ", "MLflow."
    ]
    for token in stream_chunks:
        await asyncio.sleep(0.04)  # ~25 tokens/s
        yield token


async def run_action_sandbox_probe():
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    settings.ensure_directories()

    mlflow.set_tracking_uri(settings.get_mlflow_uri())
    mlflow.set_experiment(settings.mlflow_experiment_name)

    print("\n========================================================")
    print("🛡️ BLOCO 4 — PROBE DE SANDBOX, IDEMPOTÊNCIA E STREAMING ANTECIPADO")
    print("========================================================")
    print(f"Sandbox SQLite: {sandbox.db_path}\n")

    with mlflow.start_run(run_name="probe_bloco_4_sandbox_idempotency"):
        # -------------------------------------------------------------
        # 1. TESTE DE ESCRITA OPERACIONAL E IDEMPOTÊNCIA
        # -------------------------------------------------------------
        print("--- [FASE 1: Execução e Idempotência de Jobs] ---")
        import uuid
        idempotency_key = f"req_user_test_{uuid.uuid4().hex[:6]}"
        
        # Primeira chamada: deve criar job
        res_1 = execute_trigger_experiment("05_voice_agents", "local_light", idempotency_key=idempotency_key)
        print(f"Disparo 1: {res_1.data['message']}")
        assert res_1.status == "success"
        assert res_1.data["is_new"] is True, "Primeira chamada deve criar um job novo!"
        job_id = res_1.data["job_id"]

        # Segunda chamada com MESMA chave: deve reaproveitar job sem duplicar
        res_2 = execute_trigger_experiment("05_voice_agents", "local_light", idempotency_key=idempotency_key)
        print(f"Disparo 2 (repetição com mesma chave): {res_2.data['message']}")
        assert res_2.status == "success"
        assert res_2.data["is_new"] is False, "Segunda chamada NÃO pode criar um novo job!"
        assert res_2.data["job_id"] == job_id, "O job_id retornado deve ser estritamente o mesmo!"
        print("✅ Idempotência validada: nenhuma execução duplicada gerada.\n")

        # -------------------------------------------------------------
        # 2. TESTE DE ORQUESTRAÇÃO SAGA (TRANSAÇÃO COMPENSATÓRIA)
        # -------------------------------------------------------------
        print("--- [FASE 2: Transação Compensatória SAGA (Cancelamento)] ---")
        cancel_res = execute_cancel_experiment(job_id, reason="Interrupção / Cancelamento pelo usuário")
        print(f"Cancelamento SAGA: {cancel_res.data['message']}")
        assert cancel_res.status == "success"
        assert cancel_res.data["was_cancelled"] is True

        # Verificar se o estado no banco de dados SQLite mudou para 'cancelled'
        jobs_in_db = sandbox.list_jobs()
        matched = [j for j in jobs_in_db if j.job_id == job_id]
        assert len(matched) == 1
        assert matched[0].status == "cancelled", "Status no SQLite deve estar 'cancelled'"
        print("✅ Transação compensatória SAGA validada com sucesso no SQLite.\n")

        # -------------------------------------------------------------
        # 3. STREAMING ANTECIPADO (CODEX PROXY PATTERN)
        # -------------------------------------------------------------
        print("--- [FASE 3: Streaming Antecipado — Iniciar TTS sem esperar o LLM] ---")
        chunker = TextSentenceChunker(first_chunk_min_words=2)
        barge_in_ctrl = BargeInController()
        barge_in_ctrl.start_turn("turn_stream_codex")

        tts_dispatched_events = []
        t_stream_start = time.perf_counter()
        first_tts_dispatch_time_ms = 0.0

        async def on_sentence_ready(event: TextChunkEvent):
            nonlocal first_tts_dispatch_time_ms
            elapsed_ms = (time.perf_counter() - t_stream_start) * 1000.0
            if not tts_dispatched_events:
                first_tts_dispatch_time_ms = elapsed_ms
            tts_dispatched_events.append((event, elapsed_ms))
            print(f"🚀 [TTS Background Dispatched] Sentença {event.chunk_index} disparada aos {elapsed_ms:.1f} ms: '{event.text_content}'")
            # Simula síntese imediata
            await asyncio.sleep(0.01)

        # Executa o pipeline de streaming
        await stream_and_chunk_response(
            token_stream=mock_codex_token_generator(),
            session_id="session_codex",
            turn_id="turn_stream_codex",
            chunker=chunker,
            barge_in_ctrl=barge_in_ctrl,
            on_sentence_ready=on_sentence_ready
        )

        total_llm_time_ms = (time.perf_counter() - t_stream_start) * 1000.0
        time_saved_ms = total_llm_time_ms - first_tts_dispatch_time_ms

        print(f"\n📊 Total de sentenças enviadas ao TTS: {len(tts_dispatched_events)}")
        print(f"⏱️  Primeiro áudio despachado aos: {first_tts_dispatch_time_ms:.1f} ms")
        print(f"⏱️  LLM terminou geração total aos: {total_llm_time_ms:.1f} ms")
        print(f"💡 Tempo ganho com streaming sobreposto (Pipeline Overlap): {time_saved_ms:.1f} ms")

        assert first_tts_dispatch_time_ms < 150.0, "Primeira sentença deve ser despachada quase imediatamente"
        assert time_saved_ms > 400.0, "Deveria ter economizado mais de 400ms mascarando a síntese com a geração"

        # -------------------------------------------------------------
        # 4. REGISTRO NO MLFLOW
        # -------------------------------------------------------------
        mlflow.log_metrics({
            "first_tts_dispatch_ms": first_tts_dispatch_time_ms,
            "total_llm_generation_ms": total_llm_time_ms,
            "pipeline_overlap_gain_ms": time_saved_ms,
            "idempotency_verified": 1,
            "saga_compensation_verified": 1,
        })

        print("\n========================================================")
        print("✅ PROBE DO BLOCO 4 CONCLUÍDO COM SUCESSO!")
        print("Sandbox SQLite, Idempotência, SAGA e Streaming Antecipado 100% validados.")
        print("========================================================\n")


if __name__ == "__main__":
    asyncio.run(run_action_sandbox_probe())
