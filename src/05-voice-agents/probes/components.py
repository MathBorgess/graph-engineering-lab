"""Probe do Bloco 0: Verificação isolada de STT, TTS e telemetria de recursos com MLflow."""

import os
import sys
import time
import subprocess
from pathlib import Path
import psutil
import soundfile as sf
import mlflow

# Garantir que voice_lab esteja no PYTHONPATH
current_dir = Path(__file__).resolve().parent
package_root = current_dir.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from voice_lab.config import settings


def get_process_memory_mb() -> float:
    process = psutil.Process()
    return process.memory_info().rss / (1024 * 1024)


def get_system_swap_mb() -> float:
    return psutil.swap_memory().used / (1024 * 1024)


def generate_fixture_audio(output_path: Path, text: str) -> None:
    """Gera fixture WAV mono 16kHz usando a voz pt_BR nativa do macOS."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_aiff = output_path.with_suffix(".aiff")
    
    subprocess.run(
        ["say", "-v", "Luciana", text, "-o", str(temp_aiff)],
        check=True
    )
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(temp_aiff), str(output_path)],
        check=True
    )
    if temp_aiff.exists():
        temp_aiff.unlink()


def run_probe():
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    settings.ensure_directories()
    
    # Configurar MLflow local com backend SQLite
    tracking_uri = settings.get_mlflow_uri()
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)
    
    fixture_path = settings.artifacts_dir / "fixtures" / "test_prompt_pt.wav"
    ground_truth = "Assistente de operações do Graph Engineering Lab pronto."
    
    if not fixture_path.exists():
        print(f"[Fixture] Gerando áudio de referência em {fixture_path}...")
        generate_fixture_audio(fixture_path, ground_truth)
    
    audio_info = sf.info(str(fixture_path))
    audio_duration_s = audio_info.duration
    
    print("\n========================================================")
    print("🔍 BLOCO 0 — PROBE DE COMPONENTES E TELEMETRIA DE SISTEMA")
    print("========================================================")
    print(f"Host: Apple M2 | Memória Total: {psutil.virtual_memory().total / (1024**3):.1f} GiB")
    print(f"Swap em uso inicial: {get_system_swap_mb():.1f} MB")
    print(f"RAM inicial do processo: {get_process_memory_mb():.1f} MB")
    print(f"Áudio de teste: {audio_duration_s:.2f} s ({audio_info.samplerate} Hz, {audio_info.channels} canal)")
    print(f"Ground truth: '{ground_truth}'\n")

    with mlflow.start_run(run_name="probe_bloco_0_components"):
        # 1. Parâmetros do ensaio
        mlflow.log_params({
            "profile": settings.profile.value,
            "whisper_model": settings.whisper_model,
            "audio_duration_s": audio_duration_s,
            "ground_truth": ground_truth,
            "os": sys.platform,
            "python_version": sys.version.split()[0],
        })

        # ---------------------------------------------------------
        # 2. STT Probe: Whisper MLX Baseline (sem prompt de jargão)
        # ---------------------------------------------------------
        import mlx_whisper

        ram_before_stt = get_process_memory_mb()
        t0 = time.perf_counter()
        res_baseline = mlx_whisper.transcribe(
            str(fixture_path),
            path_or_hf_repo=settings.whisper_model,
            language=settings.language,
        )
        stt_baseline_duration = time.perf_counter() - t0
        ram_after_stt = get_process_memory_mb()
        
        text_baseline = res_baseline.get("text", "").strip()
        rtf_stt_baseline = stt_baseline_duration / audio_duration_s

        print(f"⏱️  [STT Baseline] Tempo: {stt_baseline_duration:.3f} s (RTF: {rtf_stt_baseline:.2f}x)")
        print(f"   Transcrição: '{text_baseline}'")
        print(f"   Delta RAM: +{ram_after_stt - ram_before_stt:.1f} MB (Total processo: {ram_after_stt:.1f} MB)\n")

        # ---------------------------------------------------------
        # 3. STT Probe: Whisper MLX com `initial_prompt` (Mitigação de jargão)
        # ---------------------------------------------------------
        prompt_jargon = "Graph Engineering Lab, LangGraph, specs, worktree, jobs."
        t0 = time.perf_counter()
        res_prompted = mlx_whisper.transcribe(
            str(fixture_path),
            path_or_hf_repo=settings.whisper_model,
            language=settings.language,
            initial_prompt=prompt_jargon,
        )
        stt_prompted_duration = time.perf_counter() - t0
        text_prompted = res_prompted.get("text", "").strip()

        print(f"⏱️  [STT Com Prompt de Vocabulário] Tempo: {stt_prompted_duration:.3f} s")
        print(f"   Prompt injetado: '{prompt_jargon}'")
        print(f"   Transcrição com prompt: '{text_prompted}'\n")

        # ---------------------------------------------------------
        # 4. TTS Probe: Síntese de resposta
        # ---------------------------------------------------------
        tts_response_text = "Assistente do laboratório ativo. Telemetria e estado registrados no MLflow."
        tts_output_path = settings.artifacts_dir / "probes" / "tts_probe_output.wav"
        tts_output_path.parent.mkdir(parents=True, exist_ok=True)

        ram_before_tts = get_process_memory_mb()
        t0 = time.perf_counter()
        generate_fixture_audio(tts_output_path, tts_response_text)
        tts_duration = time.perf_counter() - t0
        ram_after_tts = get_process_memory_mb()

        tts_info = sf.info(str(tts_output_path))
        rtf_tts = tts_duration / tts_info.duration

        print(f"⏱️  [TTS Síntese] Tempo: {tts_duration:.3f} s (Áudio gerado: {tts_info.duration:.2f} s, RTF: {rtf_tts:.2f}x)")
        print(f"   Texto sintetizado: '{tts_response_text}'")
        print(f"   Delta RAM: +{ram_after_tts - ram_before_tts:.1f} MB\n")

        # ---------------------------------------------------------
        # 5. Registro de Métricas e Artefatos no MLflow
        # ---------------------------------------------------------
        final_swap_mb = get_system_swap_mb()
        final_ram_mb = get_process_memory_mb()

        mlflow.log_metrics({
            "stt_baseline_duration_s": stt_baseline_duration,
            "stt_baseline_rtf": rtf_stt_baseline,
            "stt_prompted_duration_s": stt_prompted_duration,
            "tts_duration_s": tts_duration,
            "tts_rtf": rtf_tts,
            "tts_audio_duration_s": tts_info.duration,
            "ram_process_final_mb": final_ram_mb,
            "ram_process_delta_mb": final_ram_mb - ram_before_stt,
            "system_swap_mb": final_swap_mb,
        })

        mlflow.log_text(f"Baseline: {text_baseline}\nPrompted: {text_prompted}\nGround Truth: {ground_truth}", "transcription_comparison.txt")
        mlflow.log_artifact(str(fixture_path), artifact_path="audio_fixtures")
        mlflow.log_artifact(str(tts_output_path), artifact_path="audio_fixtures")

        print("========================================================")
        print("✅ PROBE DO BLOCO 0 CONCLUÍDO COM SUCESSO!")
        print(f"📊 Run MLflow registrado em: {tracking_uri}")
        print(f"💾 Swap total em uso: {final_swap_mb:.1f} MB | RAM Processo: {final_ram_mb:.1f} MB")
        print("========================================================\n")


if __name__ == "__main__":
    run_probe()
