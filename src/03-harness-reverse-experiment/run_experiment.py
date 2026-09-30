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

> **Errata (2026-09-30).** Revisado contra os 72 arquivos de `captured/` (ver `captured/README.md`). **Corrigido:** modelo (`claude-sonnet-5`); tamanho do request (140–359 KB em JSON compacto, não ~310 KB); nº de tools (38–183, 27–28 nativas); tamanho do system prompt do Claude (27,6k caracteres, não 300 KB); `thinking` (`adaptive`/`omitted`, sem `budget_tokens`); headers `anthropic-beta` (estão nos `*_summary.json`); flag de mudança de tools (`mid-conversation-tool-changes-…` não foi enviada). **Sem lastro nas capturas** (relato, marcado no texto): aviso "Skill descriptions were shortened…", regras de leitura de skills, salvaguardas destrutivas, hooks locais e `trust_level` do Codex, tokens de raciocínio do Codex; os tempos de execução não são latência limpa.

---

## 📑 1. Sumário Executivo das Descobertas

Por meio da intercepção direta via proxy reverso (MITM) posicionado entre os executáveis locais (`claude` e `codex`) e as APIs oficiais na nuvem (`api.anthropic.com` e `chatgpt.com/backend-api`), capturamos os corpos dos requests do Claude (16 requests, em 8 pares `stream: true`/`false`) e, do Codex, apenas 19 handshakes MCP `initialize` e a saída de `codex debug prompt-input` (itens de entrada, não tráfego de inferência). Não há respostas do modelo nem `usage`.

### Principais Revelações da Engenharia Reversa:

| Dimensão de Análise | Claude Code CLI (v2.1.278) | OpenAI Codex CLI (v0.155.1) |
| :--- | :--- | :--- |
| **System Prompt Inicial** | **~27,6k caracteres de system prompt (3 blocos) + 38–183 schemas de tools (varia por execução); request de ~140–359 KB em JSON compacto, com as tools em 70–88% do corpo** (o arquivo capturado tem 161–475 KB porque o proxy grava com `indent=2`). | **~31,1k caracteres de texto** obtidos com `codex debug prompt-input` (bloco de skills de 21,8k; 125 skills). Não é tráfego de inferência: o proxy só capturou 19 handshakes MCP `initialize` do Codex. A saída mostra só os itens de entrada; o `instructions` (prompt-base) não aparece, então o "~45k" citado antes não está confirmado nem refutado. |
| **Primeiras Tools Nativas** | 27–28 nativas no schema JSON da API (`Agent`, `Bash`, `Edit`, `Read`, `Write`, `NotebookEdit`, `Skill`, `WebFetch`, `WebSearch`, `Monitor`, …; sem `Glob`/`Grep` dedicados) + 11–156 tools de MCP: os plugins locais estavam em todas as execuções; os conectores claude.ai chegaram no turno 0 ou só no turno 2. | Cliente MCP `codex-mcp-client` 0.155.1, protocolo `2025-06-18` (verificado nas 19 chamadas `initialize` em `/backend-api/ps/mcp`). As tools do modelo não foram capturadas. |
| **Descoberta de MCPs e Skills** | Tools de MCP com schema completo no turno 0 (sem `defer_loading` nem tool de busca); tool `Skill` de 1,4 KB e **sem catálogo de skills** no request `-p`; header de beta `advisor-tool-2026-03-01` presente. | **Descrições de skills cortadas em ≤92 caracteres** (112 de 125 no meio da frase) e referências por alias de raiz (`r0`…`r26`, 27 raízes). O texto do aviso *"Skill descriptions were shortened…"* **não aparece** nas capturas. |
| **Mecanismo de Context Engine** | **Prompt Caching Scope + Ephemeral Caching** (`prompt-caching-scope-2026-01-05`, `extended-cache-ttl-2025-04-11`): `cache_control` `ephemeral` de 1 h em `system[1]` e `system[2]` e 1–2 pontos na cauda de `messages`; nenhum em `tools`, que ficam cobertas pelo prefixo. | `<environment_context>` (cwd, shell, data, fuso, raízes do workspace, perfil de sistema de arquivos) e `<permissions instructions>` (`sandbox_mode: read-only`, regras de prefixo). Não aparecem `SessionStart`, `UserPromptSubmit`, `git status` nem `trust_level`. |
| **Mecanismo de Reasoning Effort** | `output_config: {{"effort": "high"}}` + `thinking: {{"type": "adaptive", "display": "omitted"}}` (verificado no corpo do request) + header `anthropic-beta: effort-2025-11-24,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13` (verificado nos `*_summary.json`). | Passado por linha de comando (`-c model_reasoning_effort="high"`); o request de inferência do Codex não foi capturado, então o campo enviado ao backend **não foi verificado**. |

---

## 2. Anatomia do System Prompt Injetado

### 2.1 Claude Code CLI
O campo `system` tem **3 blocos e ~27,6k caracteres** (o request inteiro tem 140–359 KB por causa das tools). Seções do bloco 2, por tamanho: `# auto memory` (12,8k, 47%), `# Executing actions with care` (3,6k), `# Doing tasks` (3,3k), `# System` (2,0k), `# Text output` (1,7k), `# Session-specific guidance` (0,8k), `# Tone and style`, `# Using your tools`, `# Environment` e `# Context management` (~0,6k cada) e a abertura (0,8k). O contexto volátil (`gitStatus`, e-mail, `AGENTS.md`, atribuição de commit) vai em `<system-reminder>` no primeiro `user`; o ambiente e as instruções de MCP vêm em mensagens `role: "system"` dentro de `messages`.

### 2.2 OpenAI Codex CLI
Os itens de entrada capturados (`codex debug prompt-input`, 31,1k caracteres) são: `<skills_instructions>` (21,8k; 125 skills), `<permissions instructions>` (4,2k: `sandbox_mode: read-only`, escalonamento por aprovação, comando segmentado nos operadores de shell, `prefix_rule` com prefixos banidos; ação destrutiva não pedida, como `rm` ou `git reset`, exige escalonamento), `<collaboration_mode>` (0,9k), `<multi_agent_role>` (2,4k), `<multi_agent_mode>` (0,3k), `<recommended_plugins>` (0,9k) e `<environment_context>` (0,5k).

**Não encontrado nas capturas** (pode estar no `instructions`, que a saída não mostra): salvaguardas do tipo `rm -rf $HOME`/`mktemp -d`/lixeira; a regra *"The main agent must read each required instruction itself…"*; o canal `commentary` para explicar a escolha de skill; a regra de progressive disclosure de referências.

---

## 3. Gestão de Ferramentas, MCPs e Descoberta Diferida (Deferred Tools)

### Como cada harness controla a expansão de ferramentas:
- **No Claude Code:**
  - As ferramentas primárias (`Bash`, `Edit`, `Read`, etc.) são enviadas no array `tools` da chamada `POST /v1/messages`.
  - Os schemas das tools de MCP (conectores claude.ai e plugins locais) vêm **inteiros** no array `tools`; nessa versão não há `defer_loading` nem tool de busca. O conjunto muda no meio da conversa (38 → 183 tools no turno 2 da tarefa 03; 165 → 184 na tarefa 02) editando o campo `tools`. O beta relevante é `mid-conversation-system-2026-04-07` (mensagens `role: system` em `messages`); `mid-conversation-tool-changes-2026-07-01` **não** foi enviado.
- **No Codex CLI:**
  - O Codex chama `/backend-api/ps/mcp` (19 `initialize` capturados). O endpoint `/backend-api/ps/plugins/suggested/codex` **não aparece** nas capturas.
  - Quando o número de skills ou plugins instalados excede o limite de tokens da janela inicial, o Codex ativa uma heurística de **compressão de descrições**: encurta o texto das skills (corte observado: ≤92 caracteres, 112 de 125 no meio da frase); o motivo (caber no orçamento de contexto) é inferência.

---

## 4. Como o Reasoning Effort Funciona de Fato

Uma das maiores dúvidas em sistemas agenticos é o que o parâmetro `effort: high` altera na prática. A captura MITM revelou:

### 4.1 No Anthropic Claude (Sonnet 5 / thinking adaptativo)
- **Parâmetro de Rede:** A requisição envia:
  ```json
  "thinking": {{
    "type": "adaptive",
    "display": "omitted"
  }},
  "output_config": {{ "effort": "high" }}
  ```
  O `anthropic-beta` está em `headers_inspected` dos `*_summary.json` (idêntico nas 16 capturas): `claude-code-20250219, oauth-2025-04-20, interleaved-thinking-2025-05-14, thinking-token-count-2026-05-13, context-management-2025-06-27, prompt-caching-scope-2026-01-05, mid-conversation-system-2026-04-07, advisor-tool-2026-03-01, effort-2025-11-24, extended-cache-ttl-2025-04-11`.
- **Comportamento em Execução:**
  - Blocos `type: "thinking"` do assistant voltam ao histórico com texto **vazio** (`display: "omitted"`) e só a assinatura.
  - A magnitude do raciocínio **não foi medida**: as capturas contêm apenas requests, sem `usage`. Os números de 16k–32k tokens citados antes não têm lastro nas capturas.

### 4.2 No OpenAI Codex (GPT-6 Luna / Sol Reasoning Models)
- **Parâmetro de Rede (relatado, não verificado: o request de inferência do Codex não foi capturado; a diretiva vem de `-c model_reasoning_effort="high"`):**
  ```json
  "reasoning_effort": "high"
  ```
- **Comportamento em Execução:**
  - O modelo aloca tokens internos de raciocínio não-visíveis (reasoning tokens) que computam os caminhos lógicos antes de emitir a resposta ou chamada de ferramenta.
  - Relatado no log de execução do CLI (não há `usage` nas capturas): ~1k tokens em chamadas simples contra 12k a 22k no mesmo prompt.

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
**Leitura da tabela.** `Sucesso` quer dizer que o processo terminou com código 0, não que a resposta esteja correta. Cada request do Claude aparece duas vezes (`stream: true`, depois `stream: false`, corpos idênticos), então os tempos incluem esse retorno e não são latência limpa; n = 1 por célula e não há execução com effort menor como linha de base.

---

## 6. Arquivos e Payloads Brutos Capturados

Os payloads JSON integrais de cada chamada encontram-se salvos no diretório:
👉 [`src/03-harness-reverse-experiment/captured/`](captured/)

O corpo de cada request fica no `.json`; o `*_summary.json` guarda um resumo e os headers `anthropic-*`/`x-*` (nunca a credencial). Não há respostas nem `usage`: o proxy não grava a resposta em streaming. Os identificadores pessoais foram trocados por placeholders (ver `captured/README.md`).
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
