"""Runner Interativo Speech-to-Speech (S2S) para terminal.

Permite falar pelo microfone do Mac e ouvir o retorno em voz natural brasileira
através do pipeline completo: Microfone -> Whisper MLX -> LangGraph -> Kokoro ONNX -> Alto-falante.
"""

import sys
import time
import queue
import tempfile
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
import soundfile as sf
import sounddevice as sd
from langchain_core.messages import HumanMessage

from voice_lab.config import settings
from voice_lab.graph.checkpoints import get_checkpointer
from voice_lab.audio.stream import TextSentenceChunker, BargeInController
from voice_lab.audio.tts import speak_text, get_kokoro_engine
from voice_lab.skills.policy_knowledge import LEARNED_DOMAIN_PROMPT

import mlx_whisper


def flush_stdin() -> None:
    """Descarta caracteres residuais no buffer do teclado (stdin) para evitar falsos disparos."""
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def detect_audio_devices() -> Tuple[int, str, int, str]:
    """Detecta automaticamente os dispositivos de microfone e alto-falante ideais do macOS."""
    devices = sd.query_devices()
    input_idx = None
    input_name = "Padrão"
    output_idx = None
    output_name = "Padrão"

    # 1. Busca microfone embutido MacBook Air / Pro (evita microfone remoto do iPhone / continuidade em repouso)
    for idx, d in enumerate(devices):
        if d["max_input_channels"] > 0 and "macbook" in d["name"].lower():
            input_idx = idx
            input_name = d["name"]
            break

    if input_idx is None:
        for idx, d in enumerate(devices):
            if d["max_input_channels"] > 0 and any(k in d["name"].lower() for k in ["builtin", "internal", "microfone"]):
                input_idx = idx
                input_name = d["name"]
                break

    if input_idx is None:
        def_in = sd.default.device[0]
        if def_in >= 0 and def_in < len(devices) and devices[def_in]["max_input_channels"] > 0:
            input_idx = def_in
            input_name = devices[def_in]["name"]

    # 2. Busca saída de áudio (alto-falantes MacBook ou saída padrão)
    for idx, d in enumerate(devices):
        if d["max_output_channels"] > 0 and "macbook" in d["name"].lower():
            output_idx = idx
            output_name = d["name"]
            break

    if output_idx is None:
        def_out = sd.default.device[1]
        if def_out >= 0 and def_out < len(devices) and devices[def_out]["max_output_channels"] > 0:
            output_idx = def_out
            output_name = devices[def_out]["name"]

    return (
        input_idx if input_idx is not None else 0,
        input_name,
        output_idx if output_idx is not None else 1,
        output_name,
    )


def warmup_audio_hardware(device_idx: int, sample_rate: int = 16000) -> bool:
    """Pré-aquece a unidade CoreAudio AUHAL para evitar o erro 'Audio Hardware Not Running' (-9986)."""
    def _dummy(indata, frames, time_info, status):
        pass

    for attempt in range(3):
        try:
            stream = sd.InputStream(
                device=device_idx,
                samplerate=sample_rate,
                channels=1,
                callback=_dummy,
            )
            stream.start()
            stream.stop()
            stream.close()
            return True
        except Exception:
            time.sleep(0.15)
    return False


def record_audio_push_to_talk(
    device_idx: int,
    sample_rate: int = 16000,
) -> Tuple[np.ndarray, Optional[str]]:
    """Permite falar pressionando ENTER ou digitar diretamente a instrução no terminal."""
    flush_stdin()
    print("\n👉 Pressione [ENTER] para COMEÇAR a falar (ou digite seu comando aqui): ", end="", flush=True)
    user_typed = sys.stdin.readline().strip()

    if user_typed:
        return np.array([], dtype="float32"), user_typed

    audio_queue: queue.Queue = queue.Queue()

    def callback(indata, frames, time_info, status):
        audio_queue.put(indata.copy())

    print("🔴 Gravando... Fale no microfone agora! (Pressione [ENTER] para concluir fala): ", end="", flush=True)

    stream = None
    for attempt in range(3):
        try:
            stream = sd.InputStream(
                device=device_idx,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                callback=callback,
            )
            stream.start()
            break
        except Exception as e:
            if attempt == 2:
                print(f"\n⚠️ Falha ao abrir microfone ({e}).")
                print("💡 Certifique-se de conceder acesso ao microfone em:")
                print("   Ajustes do Sistema -> Privacidade e Segurança -> Microfone")
                return np.array([], dtype="float32"), None
            time.sleep(0.2)

    t_start = time.time()
    try:
        sys.stdin.readline()
    finally:
        if stream:
            stream.stop()
            stream.close()

    elapsed = time.time() - t_start
    print("⏹️ Gravação concluída. Processando fala...")

    if elapsed < 0.25:
        return np.array([], dtype="float32"), None

    chunks = []
    while not audio_queue.empty():
        chunks.append(audio_queue.get())

    if not chunks:
        return np.array([], dtype="float32"), None

    return np.concatenate(chunks, axis=0), None


def run_interactive_s2s():
    settings.ensure_directories()
    thread_id = "live_user_voice_session"
    config = {"configurable": {"thread_id": thread_id}}

    in_idx, in_name, out_idx, out_name = detect_audio_devices()
    sd.default.device = (in_idx, out_idx)

    # Pré-carrega modelo Kokoro em memória para respostas instantâneas
    tts_engine = get_kokoro_engine()
    tts_status = f"Kokoro ONNX ({settings.kokoro_voice}) — Português Natural" if tts_engine else "macOS nativo (fallback)"

    # Pré-aquecimento do hardware CoreAudio
    warmup_audio_hardware(in_idx, sample_rate=settings.stt_sample_rate)

    print("====================================================================")
    print("🎙️ GRAPH ENGINEERING LAB — ASSISTENTE DE OPERAÇÕES POR VOZ (S2S)")
    print("====================================================================")
    print("Arquitetura ativa:")
    print("  • STT: Whisper tiny (Apple Silicon MLX com dicionário de vocabulário técnico)")
    print("  • Grafo: LangGraph com Two-Phase Commit e Guardrail determinístico")
    print("  • Checkpointer: SQLite persistente em .artifacts/checkpoints.db")
    print(f"  • TTS: {tts_status}")
    print(f"  • Dispositivos: Entrada [{in_idx}] '{in_name}' | Saída [{out_idx}] '{out_name}'")
    print("--------------------------------------------------------------------")
    print("💡 Exemplos de frases que você pode falar:")
    print("  1. 'O que é barge-in nas regras do laboratório?'")
    print("  2. 'Quais experimentos estão em andamento?'")
    print("  3. 'Por favor, rode o experimento 05 no perfil local_light.'")
    print("  4. (Após a proposta): 'Sim, confirmo!' ou 'Não, cancela.'")
    print("--------------------------------------------------------------------")
    print("Digite 'sair' a qualquer momento para encerrar.\n")

    saudacao = "Assistente de operações do Graph Engineering Lab pronto. Como posso ajudar?"
    print(f"🤖 Agente: {saudacao}")
    speak_text(saudacao)

    from voice_lab.graph.builder import build_voice_graph

    with get_checkpointer() as checkpointer:
        graph = build_voice_graph(checkpointer=checkpointer)

        while True:
            try:
                audio_data, typed_text = record_audio_push_to_talk(
                    device_idx=in_idx,
                    sample_rate=settings.stt_sample_rate,
                )

                transcript = ""
                stt_latency = 0.0

                if typed_text:
                    transcript = typed_text
                elif len(audio_data) >= 1600:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        temp_audio_file = Path(f.name)
                        sf.write(str(temp_audio_file), audio_data, settings.stt_sample_rate)

                    t_stt = time.perf_counter()
                    stt_res = mlx_whisper.transcribe(
                        str(temp_audio_file),
                        path_or_hf_repo=settings.whisper_model,
                        language=settings.language,
                        initial_prompt=LEARNED_DOMAIN_PROMPT,
                    )
                    stt_latency = (time.perf_counter() - t_stt) * 1000.0
                    transcript = stt_res.get("text", "").strip()

                    if temp_audio_file.exists():
                        temp_audio_file.unlink()
                else:
                    print("⚠️ Áudio muito curto ou vazio. Tente falar novamente ou digite a frase.")
                    continue

                if not transcript:
                    print("⚠️ Nenhuma fala compreensível detectada. Tente falar mais próximo do microfone.")
                    continue

                prefix = "⌨️ Você digitou" if typed_text else "🗣️ Você disse"
                stt_info = "" if typed_text else f" (STT: {stt_latency:.0f} ms)"
                print(f"\n{prefix}: \"{transcript}\"{stt_info}")

                if transcript.lower() in ["sair", "sair.", "tchau", "encerrar"]:
                    despedida = "Sessão de voz encerrada. Até logo!"
                    print(f"🤖 Agente: {despedida}")
                    speak_text(despedida)
                    break

                t_graph = time.perf_counter()
                state_out = graph.invoke(
                    {"messages": [HumanMessage(content=transcript)]},
                    config=config,
                )
                graph_latency = (time.perf_counter() - t_graph) * 1000.0

                agent_message = state_out["messages"][-1].content
                pending = state_out.get("pending_proposal")
                last_tool = state_out.get("last_tool_result")

                print(f"🤖 Agente: \"{agent_message}\" (Grafo: {graph_latency:.0f} ms)")

                if pending:
                    print(f"   [Estado Pendente]: Proposta {pending.proposal_id} ({pending.tool_name}) aguardando confirmação.")
                elif last_tool:
                    print(f"   [Resultado Operacional]: {last_tool.tool_name} -> {last_tool.status}")

                t_tts = time.perf_counter()
                speak_text(agent_message)
                tts_latency = (time.perf_counter() - t_tts) * 1000.0
                print(f"🔊 Áudio reproduzido (TTS: {tts_latency:.0f} ms)")

            except KeyboardInterrupt:
                print("\n\nSessão interrompida pelo usuário.")
                break
            except Exception as e:
                print(f"\n❌ Erro durante o processamento do turno: {e}")


if __name__ == "__main__":
    run_interactive_s2s()
