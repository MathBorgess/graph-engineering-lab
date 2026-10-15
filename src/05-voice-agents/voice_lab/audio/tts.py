"""Módulo de Síntese de Voz (TTS) com Kokoro ONNX em Português (PT-BR) e suporte a Barge-in."""

import time
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import numpy as np
import soundfile as sf
import sounddevice as sd

from voice_lab.audio.stream import BargeInController
from voice_lab.config import settings

_KOKORO_ENGINE = None


def get_kokoro_engine():
    """Retorna uma instância singleton da engine Kokoro ONNX."""
    global _KOKORO_ENGINE
    if _KOKORO_ENGINE is None:
        try:
            import kokoro_onnx

            model_path = str(settings.kokoro_model_path)
            voices_path = str(settings.kokoro_voices_path)

            if Path(model_path).exists() and Path(voices_path).exists():
                _KOKORO_ENGINE = kokoro_onnx.Kokoro(
                    model_path=model_path,
                    voices_path=voices_path,
                )
            else:
                _KOKORO_ENGINE = False
        except Exception as e:
            print(f"[TTS Warning] Falha ao inicializar Kokoro ONNX: {e}")
            _KOKORO_ENGINE = False

    return _KOKORO_ENGINE if _KOKORO_ENGINE is not False else None


def synthesize_speech_samples(
    text: str,
    voice: Optional[str] = None,
    speed: float = 1.0,
    lang: str = "pt-br",
) -> tuple[np.ndarray, int]:
    """Sintetiza texto em array de amostras float32 a 24kHz usando Kokoro ONNX.
    
    Retorna (samples, sample_rate).
    """
    clean_text = text.strip()
    if not clean_text:
        return np.zeros(0, dtype=np.float32), settings.tts_sample_rate

    voice_name = voice or settings.kokoro_voice
    engine = get_kokoro_engine()

    if engine is not None:
        try:
            samples, sr = engine.create(
                clean_text,
                voice=voice_name,
                speed=speed,
                lang=lang,
            )
            return samples, sr
        except Exception as e:
            print(f"[TTS Warning] Kokoro falhou ({e}), usando fallback nativo...")

    # Fallback para macOS say se Kokoro não estiver disponível
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_wav = Path(f.name)
    try:
        temp_aiff = temp_wav.with_suffix(".aiff")
        subprocess.run(["say", "-v", "Luciana", clean_text, "-o", str(temp_aiff)], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", str(temp_aiff), str(temp_wav)], check=True)
        if temp_aiff.exists():
            temp_aiff.unlink()
        data, sr = sf.read(str(temp_wav), dtype="float32")
        return data, sr
    finally:
        if temp_wav.exists():
            temp_wav.unlink()


def synthesize_speech_wav(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    speed: float = 1.0,
    lang: str = "pt-br",
) -> None:
    """Sintetiza áudio e salva diretamente em arquivo WAV 24kHz."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples, sr = synthesize_speech_samples(text, voice=voice, speed=speed, lang=lang)
    sf.write(str(output_path), samples, sr)


def play_audio_samples(
    audio_data: np.ndarray,
    sample_rate: int = 24000,
    barge_in_ctrl: Optional[BargeInController] = None,
) -> float:
    """Reproduz amostras de áudio no alto-falante com interrupção instantânea por barge-in."""
    if len(audio_data) == 0:
        return 0.0

    duration = len(audio_data) / sample_rate

    if barge_in_ctrl and barge_in_ctrl.is_cancelled:
        return 0.0

    sd.play(audio_data, sample_rate)

    t0 = time.time()
    try:
        while sd.get_stream().active:
            if barge_in_ctrl and barge_in_ctrl.is_cancelled:
                sd.stop()
                break
            time.sleep(0.02)
    except Exception:
        pass

    return min(time.time() - t0, duration)


def play_audio_file(wav_path: Path, barge_in_ctrl: Optional[BargeInController] = None) -> float:
    """Reproduz um arquivo WAV nos alto-falantes com monitoramento de cancelamento por Barge-in."""
    data, fs = sf.read(str(wav_path), dtype="float32")
    return play_audio_samples(data, fs, barge_in_ctrl=barge_in_ctrl)


def speak_text(
    text: str,
    barge_in_ctrl: Optional[BargeInController] = None,
    voice: Optional[str] = None,
    speed: float = 1.0,
) -> float:
    """Atalho completo: sintetiza o texto com Kokoro ONNX PT-BR e reproduz com suporte a barge-in."""
    samples, sr = synthesize_speech_samples(text, voice=voice, speed=speed)
    return play_audio_samples(samples, sample_rate=sr, barge_in_ctrl=barge_in_ctrl)
