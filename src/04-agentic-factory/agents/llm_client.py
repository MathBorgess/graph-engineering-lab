"""LLM Client unificado para a Rodada 3 da Fábrica Agêntica.

Modelos oficiais:
- Worker: gpt-6-luna via proxy local Codex (:8000)
- Spec Agent & Juízes: claude-sonnet-5-5 via Claude CLI oficial

Métricas:
- Registra modelo, rota, tokens de entrada/saída e latência em cada chamada.
"""

import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(enc.encode(text or ""))
except Exception:
    def count_tokens(text: str) -> int:
        return max(1, len(text or "") // 4)


@dataclass
class LLMCallRecord:
    model: str
    route: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    content: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CLAUDE_BIN = "/Users/matheusborges/.local/bin/claude"


def invoke_sonnet(prompt: str, system: Optional[str] = None) -> LLMCallRecord:
    """Invoca o Claude Sonnet 5.5 via Claude CLI oficial com registro de tokens."""
    if not Path(CLAUDE_BIN).exists():
        raise RuntimeError(f"Claude CLI não encontrado em {CLAUDE_BIN}. Sonnet 5.5 inacessível!")

    full_prompt = prompt
    if system:
        full_prompt = f"System Instructions:\n{system}\n\nTask:\n{prompt}"

    p_tokens = count_tokens(full_prompt)
    start_time = time.time()

    # Passa prompt via stdin ou argumento
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "--safe-mode", "--model", "sonnet", "-p", "-"],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timeout ao invocar Claude Sonnet 5.5 via CLI.")

    latency_ms = round((time.time() - start_time) * 1000, 1)

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"Falha na execução do Claude Sonnet 5.5 (code {proc.returncode}): {err_msg}")

    content = proc.stdout.strip()
    c_tokens = count_tokens(content)

    return LLMCallRecord(
        model="claude-sonnet-5-5",
        route="claude_cli_subscription",
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
        total_tokens=p_tokens + c_tokens,
        latency_ms=latency_ms,
        content=content,
    )


def invoke_worker_codex(prompt: str, system: Optional[str] = None) -> LLMCallRecord:
    """Invoca o worker gpt-6-luna via proxy local Codex (:8000)."""
    from proxy.client import create_model

    p_tokens = count_tokens((system or "") + "\n" + prompt)
    start_time = time.time()

    llm = create_model("codex", "gpt-6-luna")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    res = llm.invoke(messages)
    latency_ms = round((time.time() - start_time) * 1000, 1)

    # Extrai texto de resposta (pode vir em lista de blocos de resposta do responses API)
    raw_content = res.content
    if isinstance(raw_content, list):
        text_parts = []
        for part in raw_content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif isinstance(part, str):
                text_parts.append(part)
        content = "\n".join(text_parts).strip()
    else:
        content = str(raw_content).strip()

    c_tokens = count_tokens(content)

    return LLMCallRecord(
        model="gpt-6-luna",
        route="codex_proxy_8000",
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
        total_tokens=p_tokens + c_tokens,
        latency_ms=latency_ms,
        content=content,
    )
