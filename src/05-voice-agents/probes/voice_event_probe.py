"""Probe do Bloco 3: Streaming de Áudio, Chunking Sintático e Interrupção (Barge-in)."""

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
from voice_lab.contracts.events import SpeechLifecycleEvent
from voice_lab.audio.stream import TextSentenceChunker, BargeInController


async def simulate_token_stream():
    """Simula o streaming de tokens emitidos pelo LLM."""
    tokens = [
        "Confirmado! ",
        "Ação ", "operacional ", "executada ", "com ", "sucesso. ",
        "Job ", "ID ", "gerado: ", "job_run_9999 ", "para ", "o ", "experimento ", "05. ",
        "Todos ", "os ", "parâmetros ", "foram ", "gravados ", "no ", "SQLite."
    ]
    for tok in tokens:
        await asyncio.sleep(0.03)  # simula 30ms por token (~33 tokens/s)
        yield tok


async def run_voice_event_probe():
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    settings.ensure_directories()

    mlflow.set_tracking_uri(settings.get_mlflow_uri())
    mlflow.set_experiment(settings.mlflow_experiment_name)

    session_id = "session_stream_001"
    turn_id = "turn_001"
    
    print("\n========================================================")
    print("🎙️ BLOCO 3 — PROBE DE STREAMING, CHUNKER E BARGE-IN")
    print("========================================================")
    print(f"Sessão: {session_id} | Turno: {turn_id}\n")

    with mlflow.start_run(run_name="probe_bloco_3_streaming_barge_in"):
        mlflow.log_params({
            "session_id": session_id,
            "turn_id": turn_id,
            "simulated_token_rate": "33 tokens/s",
        })

        # -------------------------------------------------------------
        # 1. STREAMING E CHUNKING SINTÁTICO PARA TTS
        # -------------------------------------------------------------
        print("--- [FASE 1: Streaming e Chunking Sintático] ---")
        chunker = TextSentenceChunker(first_chunk_min_words=1)
        barge_in_ctrl = BargeInController()
        barge_in_ctrl.start_turn(turn_id)

        emitted_chunks = []
        t0 = time.perf_counter()
        first_chunk_latency_ms = 0.0

        async for token in simulate_token_stream():
            events = chunker.process_token(token, session_id, turn_id)
            for ev in events:
                if not emitted_chunks:
                    first_chunk_latency_ms = (time.perf_counter() - t0) * 1000.0
                emitted_chunks.append(ev)
                print(f"⚡ [Chunk {ev.chunk_index}] TTFB: {(time.perf_counter() - t0)*1000.0:.1f} ms | Texto: '{ev.text_content}'")
                
                # Simular enqueue de chunks de áudio gerados
                dummy_pcm = b"\x00" * 4800  # ~100ms de áudio PCM
                await barge_in_ctrl.queue_audio(dummy_pcm)

        final_chunk = chunker.flush(session_id, turn_id)
        if final_chunk:
            emitted_chunks.append(final_chunk)
            print(f"⚡ [Chunk Final] Texto: '{final_chunk.text_content}'")

        total_stream_time_ms = (time.perf_counter() - t0) * 1000.0
        print(f"\n📊 Total de chunks gerados: {len(emitted_chunks)}")
        print(f"⏱️  Tempo até primeiro chunk (TTFB sintático): {first_chunk_latency_ms:.1f} ms")
        print(f"⏱️  Tempo total de streaming: {total_stream_time_ms:.1f} ms\n")

        assert len(emitted_chunks) >= 3, "Deveria ter gerado pelo menos 3 chunks sintáticos"
        assert first_chunk_latency_ms < 100.0, "Primeiro chunk deveria sair em menos de 100ms"

        # -------------------------------------------------------------
        # 2. CENÁRIO DE INTERRUPÇÃO (BARGE-IN)
        # -------------------------------------------------------------
        print("--- [FASE 2: Interrupção por Barge-in do Usuário] ---")
        # Simular nova fala do usuário enquanto o buffer ainda tem áudio
        t_barge_start = time.perf_counter()
        
        # O VAD detecta fala no microfone
        vad_event = SpeechLifecycleEvent(
            event_type="SPEECH_STARTED",
            session_id=session_id,
            turn_id="turn_002",
            duration_ms=80.0
        )
        print(f"🎤 VAD emitiu: {vad_event.event_type} (Usuário começou a falar!)")

        # Disparo imediato do Barge-in Controller
        barge_event = barge_in_ctrl.trigger_barge_in(session_id, turn_id)
        barge_latency_ms = (time.perf_counter() - t_barge_start) * 1000.0

        print(f"🛑 [Barge-in Executado] Latência de interrupção: {barge_latency_ms:.2f} ms")
        print(f"   Chunks de áudio descartados da fila: {barge_event.discarded_audio_chunks}")
        print(f"   Status de cancelamento do controller: {barge_in_ctrl.is_cancelled}\n")

        # Validação de cancelamento
        assert barge_in_ctrl.is_cancelled is True, "Controller deveria estar em estado cancelado"
        assert barge_latency_ms < 50.0, "Interrupção por barge-in deve ocorrer em menos de 50ms"
        
        # Teste de tentativa de enfileiramento pós-cancelamento
        accepted = await barge_in_ctrl.queue_audio(b"\x00" * 100)
        assert accepted is False, "Não deve aceitar áudio em turno cancelado!"

        # -------------------------------------------------------------
        # 3. REGISTRO NO MLFLOW
        # -------------------------------------------------------------
        mlflow.log_metrics({
            "first_chunk_ttfb_ms": first_chunk_latency_ms,
            "total_stream_time_ms": total_stream_time_ms,
            "total_chunks_emitted": len(emitted_chunks),
            "barge_in_stop_latency_ms": barge_latency_ms,
            "discarded_audio_chunks": barge_event.discarded_audio_chunks,
        })

        print("========================================================")
        print("✅ PROBE DO BLOCO 3 CONCLUÍDO COM SUCESSO!")
        print("Streaming sintático, TTFB reduzido e cancelamento por Barge-in 100% validados.")
        print("========================================================\n")


if __name__ == "__main__":
    asyncio.run(run_voice_event_probe())
