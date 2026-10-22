"""Base de conhecimento operacional e habilidades do laboratório."""

from typing import Any, Dict, Optional


POLICIES = {
    "barge_in": "Entrada de fala do usuário durante a fala do agente, tratada como interrupção da resposta em curso. Não deve cancelar a ação operacional já concluída.",
    "confirmacao": "Manifestação explícita do usuário vinculada aos parâmetros da alteração que o agente propõe executar. Não inferir aprovação de preferência lembrada.",
    "resultado_operacional": "Estado verificável no sistema responsável pela tarefa após uma ação, independente do que o agente disse em áudio.",
    "s2s": "Modelo que recebe e gera fala sem exigir transcrição textual externa obrigatória como intermediário da resposta.",
    "cascata": "Composição modular que transcreve fala (STT), produz resposta textual (LLM) e sintetiza fala de saída (TTS)."
}

LEARNED_DOMAIN_PROMPT = (
    "Graph Engineering Lab, LangGraph, specs, worktree, jobs, "
    "barge-in, confirmação, hybrid, local_light, Two-Phase Commit."
)


def get_policy(topic: str) -> Dict[str, Any]:
    """Recupera a definição de uma política operacional do laboratório."""
    clean_topic = topic.lower().strip().replace("-", "_").replace(" ", "_")
    
    for key, text in POLICIES.items():
        if key in clean_topic or clean_topic in key:
            return {"found": True, "topic": key, "policy": text}
            
    return {
        "found": False,
        "topic": topic,
        "available_topics": list(POLICIES.keys()),
        "message": "Tópico não encontrado na base de políticas do laboratório."
    }
