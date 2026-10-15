"""Voice Lab — Experimento 05: Agente de Voz com LangGraph, LiveKit e MLflow."""

from voice_lab.config import settings
from voice_lab.contracts.state import (
    ConversationState,
    ActionProposal,
    ToolResult,
    VoiceTurn,
)
from voice_lab.contracts.events import (
    BaseVoiceEvent,
    AudioChunkEvent,
    SpeechLifecycleEvent,
    TextChunkEvent,
    BargeInEvent,
)
from voice_lab.graph.builder import build_voice_graph
from voice_lab.graph.checkpoints import get_checkpointer, get_sqlite_connection
from voice_lab.tools.operational_tools import (
    lookup_policy,
    list_jobs,
    execute_trigger_experiment,
    execute_cancel_experiment,
)
from voice_lab.tools.sandbox import sandbox
from voice_lab.audio.stream import TextSentenceChunker, BargeInController
from voice_lab.audio.tts import speak_text
from voice_lab.agents.runner import run_interactive_s2s

__version__ = "0.1.0"

__all__ = [
    "settings",
    "ConversationState",
    "ActionProposal",
    "ToolResult",
    "VoiceTurn",
    "BaseVoiceEvent",
    "AudioChunkEvent",
    "SpeechLifecycleEvent",
    "TextChunkEvent",
    "BargeInEvent",
    "build_voice_graph",
    "get_checkpointer",
    "get_sqlite_connection",
    "lookup_policy",
    "list_jobs",
    "execute_trigger_experiment",
    "execute_cancel_experiment",
    "sandbox",
    "TextSentenceChunker",
    "BargeInController",
    "speak_text",
    "run_interactive_s2s",
]
