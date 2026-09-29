# 🔬 Experimento 03: Engenharia Reversa dos Harnesses (Claude Code vs OpenAI Codex)
## Revelando a Anatomia dos System Prompts, Descoberta de Ferramentas, Context Engine e Reasoning Effort via MITM

**Autor:** Matheus Borges  
**Repositório:** `graph-engineering-lab`  
**Data:** Setembro de 2026  
**Status:** Concluído e Validado em Laboratório  
**Relatório de Execução Detalhado:** [`src/03-harness-reverse-experiment/report.md`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/report.md)  
**Diretório de Payloads Brutos:** [`src/03-harness-reverse-experiment/captured/`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/captured/)  

---

## 📌 1. Visão Geral e Motivação

Quando executamos ferramentas de linha de comando como o `claude` (Claude Code CLI v2.1.278) ou `codex` (OpenAI Codex CLI v0.155.1), interagimos com um **harness** complexo construído pelos provedores. 

Esse harness atua como um intermediário entre a digitação do usuário e a chamada real de inferência do modelo na nuvem. A pergunta central deste experimento foi:
> **O que exatamente o harness injeta no modelo antes da nossa instrução ser processada? Como ele gerencia ferramentas, MCPs, contexto e o esforço de raciocínio (effort: high)?**

Para responder a isso de forma empírica e irrefutável, construímos um **Proxy MITM (Man-in-the-Middle) Transparente** em [`src/03-harness-reverse-experiment/mitm_proxy.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/mitm_proxy.py), configurando as variáveis de ambiente e parâmetros de override nativos de cada ferramenta:
- **Claude Code:** `ANTHROPIC_BASE_URL=http://127.0.0.1:9300`
- **Codex CLI:** `-c chatgpt_base_url="http://127.0.0.1:9300/backend-api"`

Através dessa ponte, capturamos mais de **70 payloads JSON brutos** contendo requisições, headers HTTP, metadados de telemetria e o fluxo integral de turnos.

---

## 2. A Matriz de Testes Executada

Definimos 4 sessões controladas para estressar dimensões específicas da arquitetura, comparando os modelos pequenos e intermediários de raciocínio de ponta: **Claude Sonnet 5 (`claude-sonnet-5`)** com `--effort high` e **OpenAI Codex (`gpt-6-luna`)** com `model_reasoning_effort="high"`:

```
+-----------------------------------------------------------------------------------------------+
| ID       | Dimensão Avaliada        | Modelo Claude (High)     | Modelo Codex (High)          |
+-----------------------------------------------------------------------------------------------+
| task_01  | Cold Start & Chassis     | Sonnet (Exit 0 / 15.24s) | GPT-6 Luna (Exit 0 / 20.50s) |
| task_02  | Discovery (Skills & MCP) | Sonnet (Exit 0 / 70.38s) | GPT-6 Luna (Exit 0 / 109.96s)|
| task_03  | Context Engine & Caching | Sonnet (Exit 0 / 17.06s) | GPT-6 Luna (Exit 0 / 12.20s) |
| task_04  | Reasoning Effort Dive    | Sonnet (Exit 0 / 34.25s) | GPT-6 Luna (Exit 0 / 29.17s) |
+-----------------------------------------------------------------------------------------------+
```

---

## 3. Principais Descobertas da Engenharia Reversa

### 3.1 Anatomia do System Prompt e Injeção de Chassis

Ambos os harnesses injetam um volume gigantesco de contexto inicial, mas com abordagens estilísticas e arquiteturais contrastantes:

#### No Claude Code (Anthropic):
- **Volume:** O primeiro request tem **~360 KB em JSON compacto** (o arquivo capturado tem 474 KB por estar indentado), dos quais ~27.600 caracteres são instruções de sistema e **~315 KB (88%) são schemas de 183 ferramentas**. Nas outras execuções: 331 KB / 165 tools (87% tools) e 141 KB / 38 tools (70% tools).
- **Estrutura Modular:** O prompt não é uma string monolítica, mas um array estruturado de blocos:
  1. `x-anthropic-billing-header`: Tags de faturamento e rastreamento de versão (`cc_version=2.1.278.655`).
  2. `<system-reminder>`: Injeções dinâmicas de ambiente:
     - `gitStatus`: Ramo atual, commit mais recente, arquivos modificados e autor git.
     - `userEmail`: Identificação do usuário logado.
     - `AGENTS.md`: Arquivos de regras do projeto automaticamente descobertos e embutidos.
     - Diretrizes de atribuição obrigatória para commits git (`Co-Authored-By: Claude Sonnet 5`).
  3. **Auto Memory System:** O Claude Code possui um sistema de arquivos de memória persistente em disco (`~/.claude/projects/<slug>/memory/`), categorizando memórias em `user`, `feedback`, `project` e `reference`, governadas por um índice `MEMORY.md`. O agente decide quando escrever/atualizar através de uma matriz epistêmica de gatilhos (correções, confirmações silenciosas, perfil, restrições com datas absolutas) e barreiras estritas de exclusão (Negative Boundary), detalhados em [`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/memory_and_self_improvement_study.md).

#### No OpenAI Codex:
- **Volume:** Injeção inicial em torno de **45.000 caracteres**, estruturada em seções markdown bem delimitadas.
- **Foco em Segurança e Integridade Operacional:**
  1. **Salvaguardas Destrutivas:** Proibições explícitas de comandos recursivos em `$HOME`, `/`, ou diretórios não restritos, com preferência obrigatória por `mktemp -d` e exclusão reversível (lixeira).
  2. **Regras de Autorização Implícita:** O modelo é instruído a tomar ação imediatamente sem perguntar ao usuário se a ação for de leitura, local e de baixo raio de alcance.
  3. **Sistema de Memória Transacional e Consolidação Assíncrona:** Diferente do Claude Code, o Codex desacopla completamente a gravação de memória do turno interativo do usuário. Utiliza um banco SQLite relacional (`~/.codex/memories_1.sqlite`) com tabelas `stage1_outputs` e `jobs` (fila de tarefas com leases e retries). No Stage 1, extrai `raw_memories.md` e `rollout_summaries/` com 4 seções analíticas obrigatórias (`Preference signals`, `Reusable knowledge`, `Failures and how to do differently`, `References`). No Stage 2, um processo assíncrono (**Memory Consolidation Agent**) executa o job `memory_consolidate_global`, destilando o conhecimento em `MEMORY.md` e `memory_summary.md` e efetuando commits automáticos em um repositório Git interno (`~/.codex/memories/.git`), detalhado em [`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/memory_and_self_improvement_study.md).

---

### 3.2 O Mecanismo de Descoberta Diferida (Deferred Tools, Skills e MCPs)

Como os harnesses lidam com centenas de ferramentas sem estourar o limite de tokens?

#### Claude Code:
1. **Injeção Maciça no Turno 0:** O Claude Code enviou impressionantes **183 ferramentas** no schema JSON da API logo no primeiro turno.
   - 27 ferramentas nativas: `Agent`, `Bash`, `Edit`, `Read`, `Write`, `NotebookEdit`, `CronCreate`, `WebSearch`, etc.
   - 156 ferramentas de servidores MCP (no turno 0 da tarefa 01; o número varia por execução) em nuvem e locais: identificadas pelo prefixo `mcp__<servidor>__<função>` (ex: `mcp__claude_ai_Linear__create_issue`, `mcp__plugin_speak_speak__speak`).
2. **Controle de Skills via `Skill Tool`:** As skills não são ferramentas da API; são documentos `SKILL.md`. O prompt lista os nomes e gatilhos de ~50 skills em um bloco de texto, e o modelo invoca a ferramenta nativa `Skill(skill="nome")` para carregar o conteúdo sob demanda.

#### OpenAI Codex:
1. **JSON-RPC 2.0 MCP Client:** O Codex implementa um cliente formal MCP com versão de protocolo `2025-06-18`. Ele inicializa e consulta servidores via endpoints dedicados (`/backend-api/ps/mcp` e `/backend-api/ps/plugins/...`).
2. **Heurística de Compressão de Skills (Skills Context Budget):**
   - Quando o repositório possui muitas skills, o Codex emite o aviso:  
     `"Skill descriptions were shortened to fit the skills context budget. Codex can still see every skill, but some descriptions are shorter."`
   - Ele encurta dinamicamente as descrições no cabeçalho do prompt e utiliza **aliases de caminho (root aliases como `r0`)** para permitir que o agente localize o arquivo físico sem inflar a contagem de tokens.
3. **Regra de Ouro da Leitura de Skills:** O prompt do Codex impõe uma regra estrita de orquestração:
   > *"The main agent must read each required instruction itself before acting on it. Do not delegate reading, summarizing, or interpreting skill instructions to a subagent."*

---

### 3.3 Context Engine e Gerenciamento de Cache

Uma das maiores inovações identificadas na camada de transporte da Anthropic foi o uso ostensivo de **Prompt Caching Efêmero**:

```json
"cache_control": {
  "type": "ephemeral",
  "ttl": "1h"
}
```

- Esse bloco é anexado tanto ao system prompt base quanto aos blocos de histórico e ferramentas.
- Headers beta capturados:
  - `prompt-caching-scope-2026-01-05`: Permite isolar escopos de cache entre sessões e agentes.
  - `extended-cache-ttl-2025-04-11`: Estende o tempo de retenção do cache para 1 hora.
  - `context-management-2025-06-27`: Permite ao harness solicitar ao backend a limpeza de pensamentos antigos (`"type": "clear_thinking_20251015", "keep": "all"`) para preservar espaço na janela sem perder a conclusão do raciocínio.

---

### 3.4 Desmistificando o "Effort: High" na Prática

O que realmente muda quando selecionamos `effort: high` nos dois ecossistemas?

```
+-----------------------------------------------------------------------------------------------+
| Característica         | Anthropic Claude (Sonnet)         | OpenAI Codex (GPT-6 Luna)        |
+-----------------------------------------------------------------------------------------------+
| Parâmetro de API       | "thinking": {"type": "adaptive"}  | "reasoning_effort": "high"       |
| Headers de Beta        | não capturados (`output_config.effort` no corpo) | Não aplicável (campo no payload) |
| Formato de Resposta    | Blocos explícitos type: "thinking"| Tokens internos computados       |
| Consumo de Tokens      | não medido (capturas sem `usage`) | relatado ~1.200→~22.000; não verificável nas capturas |
| Impacto de Latência    | ~15s a 35s adicionais de reflexão | ~18s a 30s adicionais            |
+-----------------------------------------------------------------------------------------------+
```

1. **No Claude:**
   - O parâmetro `effort: high` ativa o **Extended Thinking**.
   - Em streaming, o modelo devolve blocos `thinking` antes de emitir qualquer chamada de ferramenta ou resposta final. Isso permite ao modelo validar hipóteses em um rascunho invisível para o usuário final, corrigindo contradições lógicas antes de escrever a resposta.
2. **No Codex:**
   - O campo `model_reasoning_effort = "high"` faz o modelo alocar milhares de **Reasoning Tokens** na cadeia de reflexão oculta.
   - No enigma lógico testado (Tarefa 04), o modelo analisou sistematicamente todas as 6 permutações das três chaves e três agentes, descartando as 5 incompatíveis antes de emitir a dedução correta em um único parágrafo conciso.

---

## 4. Lições Aplicadas ao Nosso Laboratório (`graph-engineering-lab`)

A engenharia reversa destes harnesses consolida o projeto de nossos próprios agentes em LangGraph:

1. **Por que o MITM é superior ao Subprocess CLI:**
   - Chamar o binário do CLI via subprocess (`claude -p` / `codex exec`) obriga o seu agente a carregar os 470 KB de prompts, hooks de sessão, git scanners e 180 ferramentas que pertencem ao fluxo de terminal humano, degradando o foco do modelo.
   - O nosso proxy autenticado ([`src/subscription_proxy.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/subscription_proxy.py)) captura as credenciais e acessa a API pura sem o peso morto do harness.
2. **Arquitetura de Dois DeepAgents (Memória vs Execução):**
   - O Codex e o Claude sofrem com sobrecarga de atenção quando tentam ser arquitetos de memória e executores de ferramentas ao mesmo tempo.
   - No nosso [`src/02-deepagents-experiment/deep_agents_graph.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/02-deepagents-experiment/deep_agents_graph.py), a separação em:
     - **DeepAgent 1 (Memória & Ontologia):** Construtor de diretivas e refletor epistêmico.
     - **DeepAgent 2 (Execução):** Operador de subagentes especializados (`calculate`, `python_eval`, etc.).
   produz um raciocínio muito mais nítido, rastreável e sem poluição de contexto.
3. **Progressive Disclosure de Ferramentas:**
   - Em vez de injetar dezenas de ferramentas desde o primeiro segundo, nosso grafo utiliza ontologias e diretivas para restringir as ferramentas necessárias a cada etapa da tarefa.

---

## 5. Replicação da Memória Persistente e Auto-Revisão (`deepagents_self_improving.py`)

A partir dos achados da engenharia reversa do Auto-Memory do Claude e da consolidação em SQLite do Codex, desenvolvemos a engine de autoaperfeiçoamento do projeto:
- **Motor de Memória (`memory_system.py`)**: Implementa o índice mestre `MEMORY.md` com arquivos `<slug>.md` estruturados em YAML frontmatter (tipos: `user`, `feedback`, `project`, `reference`), com vínculos bidirecionais `[[wiki-links]]` e recuperação progressiva.
- **Catálogo de Skills Diferidas (`deferred_skills.py`)**: Expõe apenas resumos leves no prompt de planejamento; carrega o corpo de `SKILL.md` exclusivamente no momento da execução (`load_skill`).
- **Logs Estruturados & Auto-Revisão (Crítica Epistêmica)**: Cada passo de subagente é registrado com `step`, `tool`, `duration_ms` e `status`. O DeepAgent 1 executa uma auto-revisão contra o contrato da diretiva e contra as memórias de feedback recuperadas antes de sintetizar a resposta final.
- **Validação Empírica em 2 Turnos**: Comprovado que o agente grava uma regra de formatação no Turno 1 e, no Turno 2 (sem qualquer menção da regra pelo usuário), recupera a memória automaticamente e cumpre a diretriz com 100% de compliance.

Estudo completo e arquitetura detalhada em:  
👉 [**`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`**](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/memory_and_self_improvement_study.md)

---

## 6. Como Reproduzir os Experimentos

Todos os scripts, proxies e a matriz de testes foram empacotados e estão prontos para reexecução:

```bash
# 1. Executa a suíte completa de engenharia reversa via MITM:
.venv/bin/python src/03-harness-reverse-experiment/run_experiment.py

# 2. Executa o teste de autoaperfeiçoamento em 2 turnos com Context Deferred e Auto-Revisão:
.venv/bin/python src/03-harness-reverse-experiment/deepagents_self_improving.py --test

# 3. Iniciar o DeepAgents Studio Interativo com Memória Persistente:
.venv/bin/python src/03-harness-reverse-experiment/deepagents_self_improving.py

# 4. Inspecionar o índice mestre e arquivos de memória criados:
cat src/03-harness-reverse-experiment/project_memory/MEMORY.md
ls -lh src/03-harness-reverse-experiment/project_memory/
```

