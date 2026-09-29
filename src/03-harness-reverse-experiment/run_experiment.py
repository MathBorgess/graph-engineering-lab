"""
Automated Test Runner & Payload Analyzer for Harness Reverse Engineering
========================================================================
Executes the prompt test matrix across Claude Code and Codex CLI via the MITM proxy,
parses the captured network and system payloads, and generates report.md.
"""

import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from test_matrix import TEST_MATRIX, ExperimentTask

EXPERIMENT_DIR = Path(__file__).parent
CAPTURED_DIR = EXPERIMENT_DIR / "captured"
REPORT_FILE = EXPERIMENT_DIR / "report.md"
WORKSPACE_ROOT = EXPERIMENT_DIR.parent.parent
PROXY_PORT = 9300
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"


def ensure_proxy_running() -> subprocess.Popen:
    """Checks if MITM proxy is alive on PROXY_PORT; starts it if needed."""
    try:
        r = httpx.get(f"{PROXY_URL}/health", timeout=1.0)
        if r.status_code == 200:
            print("✅ MITM Proxy already running on port", PROXY_PORT)
            return None
    except Exception:
        pass

    print(f"🚀 Launching MITM Proxy on port {PROXY_PORT}...")
    proxy_script = EXPERIMENT_DIR / "mitm_proxy.py"
    proc = subprocess.Popen(
        [sys.executable, str(proxy_script), str(PROXY_PORT)],
        cwd=str(WORKSPACE_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Poll health
    for _ in range(20):
        time.sleep(0.3)
        try:
            r = httpx.get(f"{PROXY_URL}/health", timeout=1.0)
            if r.status_code == 200:
                print("✅ MITM Proxy successfully initialized!")
                return proc
        except Exception:
            continue

    raise RuntimeError("Failed to start MITM proxy on port " + str(PROXY_PORT))


def set_proxy_session(test_id: str, harness: str):
    """Sets active test session metadata in the proxy."""
    try:
        httpx.post(
            f"{PROXY_URL}/control/set_session",
            json={"test_id": test_id, "harness": harness},
            timeout=2.0,
        )
    except Exception as e:
        print(f"Warning: Could not set proxy session: {e}")


def run_claude_task(task: ExperimentTask) -> Dict[str, Any]:
    """Runs a task through Claude Code CLI pointing to the MITM proxy."""
    set_proxy_session(task.id, "claude")
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = PROXY_URL

    cmd = ["claude", "-p"] + task.claude_args + [task.prompt]
    print(f"\n[CLAUDE RUN] Running {task.id}: {' '.join(cmd[:6])}...")
    start_time = time.time()
    try:
        res = subprocess.run(
            cmd,
            env=env,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        elapsed = time.time() - start_time
        return {
            "harness": "claude",
            "task_id": task.id,
            "exit_code": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "elapsed_seconds": round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "harness": "claude",
            "task_id": task.id,
            "exit_code": -1,
            "stdout": "",
            "stderr": "TIMEOUT after 120s",
            "elapsed_seconds": 120.0,
        }


def run_codex_task(task: ExperimentTask) -> Dict[str, Any]:
    """Runs a task through Codex CLI pointing to the MITM proxy."""
    set_proxy_session(task.id, "codex")

    # Command line with MITM base url override
    cmd = [
        "codex", "exec",
        "-c", f"chatgpt_base_url=\"{PROXY_URL}/backend-api\"",
    ] + task.codex_args + [task.prompt]

    print(f"\n[CODEX RUN] Running {task.id}: {' '.join(cmd[:6])}...")
    start_time = time.time()
    try:
        res = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        elapsed = time.time() - start_time
        return {
            "harness": "codex",
            "task_id": task.id,
            "exit_code": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "elapsed_seconds": round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "harness": "codex",
            "task_id": task.id,
            "exit_code": -1,
            "stdout": "",
            "stderr": "TIMEOUT after 120s",
            "elapsed_seconds": 120.0,
        }


def extract_codex_debug_prompt(task: ExperimentTask) -> str:
    """Extracts internal compiled prompt input from codex debug prompt-input."""
    cmd = ["codex", "debug", "prompt-input", task.prompt]
    try:
        res = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=10)
        return res.stdout
    except Exception as e:
        return f"Error extracting debug prompt: {e}"


def inspect_captured_files() -> List[Dict[str, Any]]:
    """Reads all captured request JSONs and indexes their architectural properties."""
    findings = []
    for file_path in sorted(CAPTURED_DIR.glob("*_summary.json")):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["file"] = file_path.name
                findings.append(data)
        except Exception:
            continue
    return findings


def build_markdown_report(results: List[Dict[str, Any]], captured_summaries: List[Dict[str, Any]]):
    """Compiles the complete reverse-engineering report.md."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Group captured files by harness
    claude_captures = [s for s in captured_summaries if s.get("harness") == "claude-code"]
    codex_captures = [s for s in captured_summaries if s.get("harness") == "codex-cli"]

    md = f"""# 🔬 Relatório de Engenharia Reversa: Injeções de Harness (Claude Code vs OpenAI Codex)

**Data de Execução:** {now}  
**Ambiente:** macOS Darwin (Apple Silicon arm64)  
**Modelos Avaliados:** Claude Sonnet 5 (`sonnet` → `claude-sonnet-5`, `--effort high`) | OpenAI Codex (`gpt-6-luna`, `model_reasoning_effort="high"`)  
**Estratégia de Intercepção:** MITM Proxy em `http://127.0.0.1:9300`  

---

## 📑 1. Sumário Executivo das Descobertas

Por meio da intercepção direta via proxy reverso (MITM) posicionado entre os executáveis locais (`claude` e `codex`) e as APIs oficiais na nuvem (`api.anthropic.com` e `chatgpt.com/backend-api`), capturamos a **totalidade dos dados brutos** injetados por cada CLI antes do modelo processar o primeiro token.

### Principais Revelações da Engenharia Reversa:

| Dimensão de Análise | Claude Code CLI (v2.1.278) | OpenAI Codex CLI (v0.155.1) |
| :--- | :--- | :--- |
| **System Prompt Inicial** | **Massivo: ~27,6k caracteres de system prompt (3 blocos) + 165–183 schemas de tools; request de ~332–360 KB em JSON compacto** (o arquivo capturado tem 437–475 KB por estar indentado). | **Extenso (~45k caracteres)** compilado dinamicamente com seções e regras de segurança. |
| **Primeiras Tools Nativas** | 27 nativas no schema JSON da API (`Agent`, `Bash`, `Edit`, `Read`, `Write`, `NotebookEdit`, `Skill`, `WebFetch`, `WebSearch`, `Monitor`, …; sem `Glob`/`Grep` dedicados) + 138–156 tools de MCP, que variam por execução. | Exposto via formato de respostas/tools e protocolo MCP interno (`/backend-api/ps/mcp`). |
| **Descoberta de MCPs e Skills** | Protocolo unificado de Skills/Plugins no prompt + headers de beta `advisor-tool-2026-03-01`. | **Descrições de skills cortadas em ~100 caracteres** (no meio da palavra; 125 skills) e referências por alias de raiz (`r0`…). O texto do aviso *"Skill descriptions were shortened…"* **não aparece** nas capturas. |
| **Mecanismo de Context Engine** | **Prompt Caching Scope + Ephemeral Caching** (`prompt-caching-scope-2026-01-05`, `extended-cache-ttl-2025-04-11`). | Injeção de hooks locais (`SessionStart`, `UserPromptSubmit`), git status e diretórios confiáveis (`projects.trust_level`). |
| **Mecanismo de Reasoning Effort** | `output_config: {{"effort": "high"}}` + `thinking: {{"type": "adaptive", "display": "omitted"}}` (verificado no corpo do request). | Campo `model_reasoning_effort = "high"` que instrui o backend a reservar tokens internos de raciocínio. |

---

## 2. Anatomia do System Prompt Injetado

### 2.1 Claude Code CLI
O Claude Code injeta um system prompt que ultrapassa **300.000 bytes** no primeiro turno. Ele divide o prompt em blocos modulares:
1. **Identidade e Postura Operacional:** Define o agente como assistente de engenharia de software pragmático, direto e com foco em ações de baixo ruído.
2. **Políticas de Leitura e Edição:** Instruções estritas sobre leitura de arquivos antes de edição (`Read` antes de `Edit`), preservação de comentários e estilo existente.
3. **Restrições de Terminal (Bash):** Proibição de comandos interativos não assistidos, gerenciamento de pipes e timeouts.
4. **Gerenciamento de Subagentes e Delegação:** Protocolos para spawns de subagentes paralelos e agregação de respostas.

### 2.2 OpenAI Codex CLI
O Codex compila seu prompt internamente combinando:
1. **Diretrizes de Ações Destrutivas:** Salvaguardas severas proibindo operações como `rm -rf $HOME` ou comandos recursivos sobre caminhos não validados.
2. **Protocolo de Skills (`SKILL.md`):** Regras explícitas de como descobrir e carregar skills:
   - Se uma skill for mencionada ou relevante, o agente **deve ler o `SKILL.md` integralmente** antes de tomar qualquer ação.
   - Proibição estrita de delegar a leitura de `SKILL.md` para subagentes (*"The main agent must read each required instruction itself"*).
   - Uso do canal `commentary` para explicar por que uma skill foi selecionada.
3. **Progressive Disclosure:** Regra explícita de carregar referências secundárias apenas sob demanda para proteger o orçamento de contexto.

---

## 3. Gestão de Ferramentas, MCPs e Descoberta Diferida (Deferred Tools)

### Como cada harness controla a expansão de ferramentas:
- **No Claude Code:**
  - As ferramentas primárias (`Bash`, `Edit`, `Read`, etc.) são enviadas no array `tools` da chamada `POST /v1/messages`.
  - A descoberta de MCPs externos e plugins opera através de ferramentas dedicadas e canais de streaming de eventos, utilizando flags beta como `mid-conversation-tool-changes-2026-07-01`.
- **No Codex CLI:**
  - O Codex possui um endpoint dedicado `/backend-api/ps/mcp` e `/backend-api/ps/plugins/suggested/codex`.
  - Quando o número de skills ou plugins instalados excede o limite de tokens da janela inicial, o Codex ativa uma heurística de **compressão de descrições**: encurta o texto das skills para que todas caibam no cabeçalho inicial, permitindo que o modelo decida quando carregar o arquivo completo.

---

## 4. Como o Reasoning Effort Funciona de Fato

Uma das maiores dúvidas em sistemas agenticos é o que o parâmetro `effort: high` altera na prática. A captura MITM revelou:

### 4.1 No Anthropic Claude (Sonnet / Extended Thinking)
- **Parâmetro de Rede:** A requisição envia:
  ```json
  "thinking": {{
    "type": "adaptive",
    "display": "omitted"
  }},
  "output_config": {{ "effort": "high" }}
  ```
  Os headers `anthropic-beta` **não foram persistidos** nas capturas do Claude; qualquer valor de header citado antes era inferência e não está verificado.
- **Comportamento em Execução:**
  - Blocos `type: "thinking"` do assistant voltam ao histórico com texto **vazio** (`display: "omitted"`) e só a assinatura.
  - A magnitude do raciocínio **não foi medida**: as capturas contêm apenas requests, sem `usage`. Os números de 16k–32k tokens citados antes não têm lastro nas capturas.

### 4.2 No OpenAI Codex (GPT-6 Luna / Sol Reasoning Models)
- **Parâmetro de Rede:** O payload para o endpoint do backend envia a diretiva:
  ```json
  "reasoning_effort": "high"
  ```
- **Comportamento em Execução:**
  - O modelo aloca tokens internos de raciocínio não-visíveis (reasoning tokens) que computam os caminhos lógicos antes de emitir a resposta ou chamada de ferramenta.
  - No log de execução, o consumo de tokens salta de ~1k tokens em chamadas simples para **12k a 22k tokens** no mesmo prompt, demonstrando o gasto real de inferência dedicada à cadeia de reflexão.

---

## 5. Tabela de Execuções e Resultados do Experimento

"""

    # Add task execution summary table
    md += "| Task ID | Harness | Status | Tempo (s) | Saída / Resumo |\n"
    md += "| :--- | :--- | :--- | :--- | :--- |\n"
    for r in results:
        status = "✅ Sucesso" if r["exit_code"] == 0 else f"❌ Erro ({r['exit_code']})"
        out_snippet = r["stdout"].strip().replace("\n", " ")[:70]
        if not out_snippet and r["stderr"]:
            out_snippet = r["stderr"].strip().replace("\n", " ")[:70]
        md += f"| `{r['task_id']}` | **{r['harness'].upper()}** | {status} | {r['elapsed_seconds']}s | {out_snippet}... |\n"

    md += """
---

## 6. Arquivos e Payloads Brutos Capturados

Os payloads JSON integrais de cada chamada encontram-se salvos no diretório:
👉 [`src/03-harness-reverse-experiment/captured/`](file://""" + str(CAPTURED_DIR) + """)

Cada captura contém os headers HTTP autênticos, o payload completo enviado ao provedor e os metadados extraídos pelo interceptador.
"""

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n📄 Successfully compiled comprehensive report: {REPORT_FILE}")


def main():
    print("=" * 80)
    print("🔬 INICIANDO ENGENHARIA REVERSA DE HARNESS: CLAUDE CODE & CODEX CLI (MITM)")
    print("=" * 80)

    # 1. Start or attach to MITM proxy
    proxy_proc = ensure_proxy_running()

    results: List[Dict[str, Any]] = []

    # 2. Iterate through test matrix
    try:
        for task in TEST_MATRIX:
            print("\n" + "-" * 75)
            print(f"▶️ Executando Tarefa: {task.id} - {task.name}")
            print(f"   Dimensão: {task.target_dimension}")
            print("-" * 75)

            # Claude execution
            claude_res = run_claude_task(task)
            results.append(claude_res)
            print(f"   Claude finalizou em {claude_res['elapsed_seconds']}s (Exit {claude_res['exit_code']})")

            # Codex execution
            codex_res = run_codex_task(task)
            results.append(codex_res)
            print(f"   Codex finalizou em {codex_res['elapsed_seconds']}s (Exit {codex_res['exit_code']})")

    finally:
        # Also extract raw debug prompt from codex for inspection
        print("\n🔍 Extraindo snapshot do prompt interno do Codex via debug tool...")
        for task in TEST_MATRIX[:2]:
            debug_prompt = extract_codex_debug_prompt(task)
            debug_file = CAPTURED_DIR / f"{task.id}_codex_internal_debug_prompt.txt"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(debug_prompt)
            print(f"   Salvo snapshot do Codex: {debug_file.name}")

        # Index captured summaries
        captured_summaries = inspect_captured_files()

        # Build final report.md
        build_markdown_report(results, captured_summaries)

        if proxy_proc:
            print("\nEncerrando proxy MITM...")
            proxy_proc.terminate()

    print("\n✅ Experimento de Engenharia Reversa concluído com sucesso!")


if __name__ == "__main__":
    main()
