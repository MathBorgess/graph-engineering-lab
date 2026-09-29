# 🔬 Relatório de Engenharia Reversa: Injeções de Harness (Claude Code vs OpenAI Codex)

**Data de Execução:** 2026-09-29 07:01:16  
**Ambiente:** macOS Darwin (Apple Silicon arm64)  
**Modelos Avaliados:** Claude 3.7 Sonnet (`sonnet`, `--effort high`) | OpenAI Codex (`gpt-6-luna`, `model_reasoning_effort="high"`)  
**Estratégia de Intercepção:** MITM Proxy em `http://127.0.0.1:9300`  

---

## 📑 1. Sumário Executivo das Descobertas

Por meio da intercepção direta via proxy reverso (MITM) posicionado entre os executáveis locais (`claude` e `codex`) e as APIs oficiais na nuvem (`api.anthropic.com` e `chatgpt.com/backend-api`), capturamos a **totalidade dos dados brutos** injetados por cada CLI antes do modelo processar o primeiro token.

### Principais Revelações da Engenharia Reversa:

| Dimensão de Análise | Claude Code CLI (v2.1.278) | OpenAI Codex CLI (v0.155.1) |
| :--- | :--- | :--- |
| **System Prompt Inicial** | **Massivo (~310 KB / ~75k caracteres)** injetado como array de blocos estruturados. | **Extenso (~45k caracteres)** compilado dinamicamente com seções e regras de segurança. |
| **Primeiras Tools Nativas** | Conjunto estrito exposto no schema JSON da API: `Bash`, `Edit`, `Read`, `Glob`, `Grep`, `Write`, `NotebookEdit`. | Exposto via formato de respostas/tools e protocolo MCP interno (`/backend-api/ps/mcp`). |
| **Descoberta de MCPs e Skills** | Protocolo unificado de Skills/Plugins no prompt + headers de beta `advisor-tool-2026-03-01`. | **Truncamento ativo de Skills** via orçamento de contexto (*"Skill descriptions were shortened..."*) e referências indexadas (`r0`). |
| **Mecanismo de Context Engine** | **Prompt Caching Scope + Ephemeral Caching** (`prompt-caching-scope-2026-01-05`, `extended-cache-ttl-2025-04-11`). | Injeção de hooks locais (`SessionStart`, `UserPromptSubmit`), git status e diretórios confiáveis (`projects.trust_level`). |
| **Mecanismo de Reasoning Effort** | Header `effort-2025-11-24` + bloco `thinking: {"type": "enabled", "budget_tokens": ...}`. | Campo `model_reasoning_effort = "high"` que instrui o backend a reservar tokens internos de raciocínio. |

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
    "type": "enabled",
    "budget_tokens": 16000
  }
  ```
  acompanhado do header:
  `anthropic-beta: effort-2025-11-24,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13`
- **Comportamento em Execução:**
  - O modelo emite blocos `type: "thinking"` contendo o fluxo de monólogo interno antes de emitir os blocos `type: "text"` ou `type: "tool_use"`.
  - Com `effort: high`, o orçamento de tokens de raciocínio é maximizado (tipicamente 16k a 32k tokens), permitindo que o modelo realize múltiplos passos de prova matemática e exploração de hipóteses sem interromper o fluxo para o usuário.

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
