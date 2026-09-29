# 🔬 Relatório de Engenharia Reversa: Injeções de Harness (Claude Code vs OpenAI Codex)

**Data de Execução:** 2026-09-29 07:01:16  
**Ambiente:** macOS Darwin (Apple Silicon arm64)  
**Modelos Avaliados:** Claude Sonnet 5 (`sonnet` → `claude-sonnet-5`, `--effort high`) | OpenAI Codex (`gpt-6-luna`, `model_reasoning_effort="high"`)  
**Estratégia de Intercepção:** MITM Proxy em `http://127.0.0.1:9300`  

---

## 📑 1. Sumário Executivo das Descobertas

Por meio da intercepção direta via proxy reverso (MITM) posicionado entre os executáveis locais (`claude` e `codex`) e as APIs oficiais na nuvem (`api.anthropic.com` e `chatgpt.com/backend-api`), capturamos a **totalidade dos dados brutos** injetados por cada CLI antes do modelo processar o primeiro token.

### Principais Revelações da Engenharia Reversa:

| Dimensão de Análise | Claude Code CLI (v2.1.278) | OpenAI Codex CLI (v0.155.1) |
| :--- | :--- | :--- |
| **System Prompt Inicial** | **Massivo: ~27,6k caracteres de system prompt (3 blocos) + 165–183 schemas de tools; request de ~332–360 KB em JSON compacto** (o arquivo capturado tem 437–475 KB por estar indentado). | **~31,1k caracteres de texto** obtidos com `codex debug prompt-input` (bloco de skills de 21,8k; 125 skills). Não é tráfego de inferência: o proxy só capturou 19 handshakes MCP `initialize` do Codex. |
| **Primeiras Tools Nativas** | 27 nativas no schema JSON da API (`Agent`, `Bash`, `Edit`, `Read`, `Write`, `NotebookEdit`, `Skill`, `WebFetch`, `WebSearch`, `Monitor`, …; sem `Glob`/`Grep` dedicados) + 138–156 tools de MCP, que variam por execução. | Exposto via formato de respostas/tools e protocolo MCP interno (`/backend-api/ps/mcp`). |
| **Descoberta de MCPs e Skills** | Protocolo unificado de Skills/Plugins no prompt + headers de beta `advisor-tool-2026-03-01`. | **Descrições de skills cortadas em ~100 caracteres** (no meio da palavra; 125 skills) e referências por alias de raiz (`r0`…). O texto do aviso *"Skill descriptions were shortened…"* **não aparece** nas capturas. |
| **Mecanismo de Context Engine** | **Prompt Caching Scope + Ephemeral Caching** (`prompt-caching-scope-2026-01-05`, `extended-cache-ttl-2025-04-11`). | Injeção de hooks locais (`SessionStart`, `UserPromptSubmit`), git status e diretórios confiáveis (`projects.trust_level`). |
| **Mecanismo de Reasoning Effort** | `output_config: {"effort": "high"}` + `thinking: {"type": "adaptive", "display": "omitted"}` (verificado no corpo do request). | Campo `model_reasoning_effort = "high"` que instrui o backend a reservar tokens internos de raciocínio. |

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
  "thinking": {
    "type": "adaptive",
    "display": "omitted"
  },
  "output_config": { "effort": "high" }
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

| Task ID | Harness | Status | Tempo (s) | Saída / Resumo |
| :--- | :--- | :--- | :--- | :--- |
| `task_01_cold_start` | **CLAUDE** | ✅ Sucesso | 15.24s | Claude Sonnet 5 (ID interno do modelo: `claude-sonnet-5`), operando co... |
| `task_01_cold_start` | **CODEX** | ✅ Sucesso | 20.5s | **Identificação:** Codex, agente baseado em GPT‑6. O identificador de ... |
| `task_02_discovery` | **CLAUDE** | ✅ Sucesso | 70.38s | Confirmado: nada disso está configurado dentro do repositório `graph-e... |
| `task_02_discovery` | **CODEX** | ✅ Sucesso | 109.96s | Sim. **Não encontrei skills ou configuração MCP dentro do projeto**: o... |
| `task_03_context_engine` | **CLAUDE** | ✅ Sucesso | 17.06s | ## Propósito das bibliotecas em `requirements.txt`  1. **API web** — `... |
| `task_03_context_engine` | **CODEX** | ✅ Sucesso | 12.2s | - **API e servidor:** FastAPI e Uvicorn criam e servem APIs web. - **V... |
| `task_04_reasoning_effort` | **CLAUDE** | ✅ Sucesso | 34.25s | ## Enigma dos Três Agentes e Três Chaves  **Premissas:** - A sempre me... |
| `task_04_reasoning_effort` | **CODEX** | ✅ Sucesso | 29.17s | Há seis distribuições possíveis das três chaves, mas as falas de A e C... |

---

## 6. Arquivos e Payloads Brutos Capturados

Os payloads JSON integrais de cada chamada encontram-se salvos no diretório:
👉 [`src/03-harness-reverse-experiment/captured/`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/captured)

Cada captura contém os headers HTTP autênticos, o payload completo enviado ao provedor e os metadados extraídos pelo interceptador.
