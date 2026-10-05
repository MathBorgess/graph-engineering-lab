"""Módulo de áudio, streaming, chunking e síntese do Voice Lab."""

from voice_lab.audio.stream import TextSentenceChunker, BargeInController
from voice_lab.audio.tts import synthesize_speech_wav, play_audio_file, speak_text
from voice_lab.audio.codex_stream import stream_and_chunk_response

__all__ = [
    "TextSentenceChunker",
    "BargeInController",
    "synthesize_speech_wav",
    "play_audio_file",
    "speak_text",
    "stream_and_chunk_response",
]
