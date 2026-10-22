"""Definições de eventos para a arquitetura assíncrona orientada a eventos (Event-Driven Voice)."""

import time
from typing import Any, Dict, Literal
from pydantic import BaseModel, Field


EventType = Literal[
    "AUDIO_FRAME_RECEIVED",
    "SPEECH_STARTED",
    "SPEECH_ENDED",
    "TRANSCRIPTION_COMPLETED",
    "TEXT_TOKEN_STREAMED",
    "TEXT_SENTENCE_READY",
    "AUDIO_SYNTHESIS_STARTED",
    "AUDIO_PLAYBACK_STARTED",
    "BARGE_IN_TRIGGERED",
    "PLAYBACK_CANCELLED",
    "TOOL_EXECUTION_TRIGGERED",
    "SAGA_COMPENSATION_TRIGGERED",
]


class BaseVoiceEvent(BaseModel):
    """Contrato base para eventos de voz com timestamp monotônico de alta precisão."""
    event_type: EventType
    session_id: str
    turn_id: str
    timestamp: float = Field(default_factory=time.perf_counter)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AudioChunkEvent(BaseVoiceEvent):
    """Chunk bruto de áudio recebido do transporte (ex: 30ms PCM)."""
    event_type: EventType = "AUDIO_FRAME_RECEIVED"
    sample_rate: int = 16000
    is_speech_probability: float = 0.0


class SpeechLifecycleEvent(BaseVoiceEvent):
    """Eventos de início ou fechamento de fala emitidos pelo VAD."""
    event_type: EventType  # SPEECH_STARTED ou SPEECH_ENDED
    duration_ms: float = 0.0


class TranscriptionEvent(BaseVoiceEvent):
    """Evento emitido após a transcrição do áudio pelo STT."""
    event_type: EventType = "TRANSCRIPTION_COMPLETED"
    transcript: str
    stt_latency_ms: float = 0.0


class TextChunkEvent(BaseVoiceEvent):
    """Sentença/chunk de texto pronta para envio ao sintetizador TTS."""
    event_type: EventType = "TEXT_SENTENCE_READY"
    chunk_index: int
    text_content: str
    is_final_chunk: bool = False


class BargeInEvent(BaseVoiceEvent):
    """Evento crítico emitido quando o usuário interrompe a resposta do agente."""
    event_type: EventType = "BARGE_IN_TRIGGERED"
    reason: str = "User speech detected during agent playback"
    interrupted_turn_id: str
    discarded_audio_chunks: int = 0
