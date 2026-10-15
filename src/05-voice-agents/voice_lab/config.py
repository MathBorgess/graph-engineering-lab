"""Configurações centrais do Experimento 05 — Voice Lab."""

from enum import Enum
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionProfile(str, Enum):
    LOCAL_LIGHT = "local_light"
    HYBRID_CONTROL = "hybrid_control"
    LOCAL_HF_PRESET = "local_hf_preset"


class VoiceLabSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOICE_LAB_",
        env_file=".env",
        extra="ignore",
    )

    # Perfil ativo
    profile: ExecutionProfile = ExecutionProfile.LOCAL_LIGHT

    # Idioma e Áudio
    language: str = "pt"
    stt_sample_rate: int = 16000
    tts_sample_rate: int = 24000

    # Modelos
    whisper_model: str = "mlx-community/whisper-tiny"
    kokoro_voice: str = "pm_alex"
    kokoro_model_path: Path = Field(
        default_factory=lambda: (
            Path(__file__).resolve().parent.parent / ".artifacts" / "models" / "kokoro" / "kokoro-v1.0.int8.onnx"
            if (Path(__file__).resolve().parent.parent / ".artifacts" / "models" / "kokoro" / "kokoro-v1.0.int8.onnx").exists()
            else Path.home() / ".cache" / "speak-mcp" / "models" / "kokoro-v1.0.int8.onnx"
        )
    )
    kokoro_voices_path: Path = Field(
        default_factory=lambda: (
            Path(__file__).resolve().parent.parent / ".artifacts" / "models" / "kokoro" / "voices-v1.0.bin"
            if (Path(__file__).resolve().parent.parent / ".artifacts" / "models" / "kokoro" / "voices-v1.0.bin").exists()
            else Path.home() / ".cache" / "speak-mcp" / "models" / "voices-v1.0.bin"
        )
    )
    
    # LLM (modo híbrido ou local)
    llm_provider: str = Field(default="openrouter", description="openrouter, openai ou mlx")
    llm_model: str = Field(default="openai/gpt-4o-mini", description="ID concreto do modelo")
    openrouter_api_key: str = Field(default="", description="Chave de API OpenRouter se híbrido")

    # Diretórios e Persistência
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    artifacts_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / ".artifacts")
    checkpoints_db: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / ".artifacts" / "checkpoints.db")
    memory_index_file: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "MEMORY.md")
    memories_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "memories")
    
    # MLflow
    mlflow_tracking_uri: str = ""
    mlflow_experiment_name: str = "05_voice_agents"

    def get_mlflow_uri(self) -> str:
        return f"sqlite:///{self.artifacts_dir / 'mlflow.db'}"

    def ensure_directories(self) -> None:
        """Garante a existência das pastas de artefatos e memórias."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)


settings = VoiceLabSettings()
