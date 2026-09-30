# 🔬 Experimento 03: Engenharia Reversa dos Harnesses (Claude Code vs OpenAI Codex)
## Revelando a Anatomia dos System Prompts, Descoberta de Ferramentas, Context Engine e Reasoning Effort via MITM

**Autor:** Matheus Borges  
**Repositório:** `graph-engineering-lab`  
**Data:** Setembro de 2026  
**Status:** Concluído; revisado em 2026-09-30 (ver Errata)  
**Relatório de Execução Detalhado:** [`src/03-harness-reverse-experiment/report.md`](../src/03-harness-reverse-experiment/report.md)  
**Diretório de Payloads Brutos:** [`src/03-harness-reverse-experiment/captured/`](../src/03-harness-reverse-experiment/captured/)  

> **Errata (2026-09-30).** Revisado contra os 72 arquivos de `captured/`. **Corrigido:** título (03, não 02); modelo (`claude-sonnet-5`); tamanhos (request de 140–359 KB compacto; 474 KB é o arquivo indentado); nº de tools (38–183; 27–28 nativas); `thinking` (`adaptive`/`omitted`, sem `budget_tokens`); headers (`anthropic-beta` completo nos `*_summary.json`, incluindo `effort-2025-11-24`); onde ficam os pontos de cache; "~50 skills no prompt" (não há catálogo no request `-p`). **Sem lastro nas capturas** (marcado no texto como *relato*): aviso "Skill descriptions were shortened…", regra de leitura de skills do Codex, salvaguardas destrutivas do Codex, pipeline de memória em SQLite, tokens de raciocínio, prompt de "~45k" caracteres. **Hipóteses não testadas:** que o harness degrade o foco do modelo; que a separação em dois DeepAgents dê raciocínio mais nítido. **Medido:** o peso do request.

---

## 📌 1. Visão Geral e Motivação

Quando executamos ferramentas de linha de comando como o `claude` (Claude Code CLI v2.1.278) ou `codex` (OpenAI Codex CLI v0.155.1), interagimos com um **harness** complexo construído pelos provedores. 

Esse harness atua como um intermediário entre a digitação do usuário e a chamada real de inferência do modelo na nuvem. A pergunta central deste experimento foi:
> **O que exatamente o harness injeta no modelo antes da nossa instrução ser processada? Como ele gerencia ferramentas, MCPs, contexto e o esforço de raciocínio (effort: high)?**

Para responder a isso de forma empírica, construímos um **Proxy MITM (Man-in-the-Middle) Transparente** em [`src/03-harness-reverse-experiment/mitm_proxy.py`](../src/03-harness-reverse-experiment/mitm_proxy.py), configurando as variáveis de ambiente e parâmetros de override nativos de cada ferramenta:
- **Claude Code:** `ANTHROPIC_BASE_URL=http://127.0.0.1:9300`
- **Codex CLI:** `-c chatgpt_base_url="http://127.0.0.1:9300/backend-api"`

Através dessa ponte, capturamos **72 arquivos**: 16 corpos de request do Claude (8 pares `stream: true`/`false`), 19 handshakes MCP `initialize` do Codex, 35 `*_summary.json` (resumo + headers `anthropic-*`/`x-*`) e 2 saídas de `codex debug prompt-input`. Não há respostas do modelo nem `usage`.

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

`Exit 0` quer dizer que o processo terminou sem erro, não que a resposta esteja certa. Cada request do Claude aparece duas vezes (`stream: true`, depois `false`), então os tempos incluem esse retorno e não são latência limpa; n = 1 por célula.

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
  3. **Auto Memory System** (a especificação inteira está no `system[2]`: 12,8k caracteres, 47% do bloco): O Claude Code possui um sistema de arquivos de memória persistente em disco (`~/.claude/projects/<slug>/memory/`), categorizando memórias em `user`, `feedback`, `project` e `reference`, governadas por um índice `MEMORY.md`. O agente decide quando escrever/atualizar através de uma matriz epistêmica de gatilhos (correções, confirmações silenciosas, perfil, restrições com datas absolutas) e barreiras estritas de exclusão (Negative Boundary), detalhados em [`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`](../src/03-harness-reverse-experiment/memory_and_self_improvement_study.md).

#### No OpenAI Codex:
- **Volume:** Prompt inicial de **~31.100 caracteres de texto** (bloco de skills de 21.800 + mensagens de papel/modo/plugins), obtido com `codex debug prompt-input` — **não** é tráfego de inferência capturado: o proxy só viu 19 handshakes MCP `initialize` do Codex.
- **Foco em Segurança e Integridade Operacional:**
  1. **Escalonamento de ação destrutiva** (verificado): ação destrutiva não pedida (`rm`, `git reset`) exige aprovação, e nunca se propõe `prefix_rule` para `rm`. *Relato, não encontrado nas capturas:* proibição de comandos recursivos em `$HOME`/`/`, `mktemp -d` e exclusão reversível (podem estar no `instructions`, que a saída não mostra).
  2. **Autorização implícita** — *relato, não encontrado nas capturas*; o que existe é `sandbox_mode: read-only` com escalonamento por aprovação.
  3. **Sistema de Memória Transacional e Consolidação Assíncrona** *(relato de inspeção de `~/.codex/`; sem artefato no repositório, e os itens de entrada capturados não trazem conteúdo de memória: hipótese, não fato verificado)*: Diferente do Claude Code, o Codex desacopla completamente a gravação de memória do turno interativo do usuário. Utiliza um banco SQLite relacional (`~/.codex/memories_1.sqlite`) com tabelas `stage1_outputs` e `jobs` (fila de tarefas com leases e retries). No Stage 1, extrai `raw_memories.md` e `rollout_summaries/` com 4 seções analíticas obrigatórias (`Preference signals`, `Reusable knowledge`, `Failures and how to do differently`, `References`). No Stage 2, um processo assíncrono (**Memory Consolidation Agent**) executa o job `memory_consolidate_global`, destilando o conhecimento em `MEMORY.md` e `memory_summary.md` e efetuando commits automáticos em um repositório Git interno (`~/.codex/memories/.git`), detalhado em [`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`](../src/03-harness-reverse-experiment/memory_and_self_improvement_study.md).

---

### 3.2 O Mecanismo de Descoberta Diferida (Deferred Tools, Skills e MCPs)

Como os harnesses lidam com centenas de ferramentas sem estourar o limite de tokens?

#### Claude Code:
1. **Injeção Maciça no Turno 0:** O Claude Code enviou **183 ferramentas** no schema JSON da API logo no primeiro turno da tarefa 01 (165 nas tarefas 02 e 04; 38 na 03, cujos conectores só chegaram no turno 2). Os schemas vêm inteiros: não há `defer_loading` nem tool de busca.
   - 27 ferramentas nativas: `Agent`, `Bash`, `Edit`, `Read`, `Write`, `NotebookEdit`, `CronCreate`, `WebSearch`, etc.
   - 156 ferramentas de servidores MCP (no turno 0 da tarefa 01; o número varia por execução) em nuvem e locais: identificadas pelo prefixo `mcp__<servidor>__<função>` (ex: `mcp__claude_ai_Linear__create_issue`, `mcp__plugin_speak_speak__speak`).
2. **Controle de Skills via `Skill Tool`:** As skills não são ferramentas da API; são documentos `SKILL.md`. Nas capturas `-p` o request **não traz catálogo de skills**: a tool `Skill` (1,4 KB) diz que as skills disponíveis aparecem em um `system-reminder`, ausente aqui. O modelo invocaria `Skill(skill="nome")` para carregar o conteúdo sob demanda (mecanismo declarado na descrição da tool, não exercitado nas capturas).

#### OpenAI Codex:
1. **JSON-RPC 2.0 MCP Client:** O Codex implementa um cliente formal MCP com versão de protocolo `2025-06-18`. Verificado: 19 chamadas `initialize` (`codex-mcp-client` 0.155.1) em `/backend-api/ps/mcp`. `/backend-api/ps/plugins/...` não aparece nas capturas.
2. **Heurística de Compressão de Skills (Skills Context Budget):**
   - O corte de descrições é **observado** (≤92 caracteres; 112 de 125 cortadas no meio da frase). O texto do aviso `"Skill descriptions were shortened to fit the skills context budget…"` **não aparece em nenhuma captura** (relato); o motivo (caber no orçamento de contexto) é inferência.
   - Ele encurta as descrições no cabeçalho do prompt e utiliza **aliases de caminho (root aliases como `r0`)** para permitir que o agente localize o arquivo físico sem inflar a contagem de tokens.
3. **Regra de Ouro da Leitura de Skills** *(texto não encontrado nas capturas; relato)*: O prompt do Codex imporia uma regra estrita de orquestração:
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

- Esse bloco aparece em `system[1]` e `system[2]` (o bloco 0, de billing, fica sem) e na cauda de `messages` (1 ponto no turno 0; 2 do turno 2 em diante). **Não** há `cache_control` em `tools`: elas são cobertas pelo prefixo, na ordem `tools → system → messages`.
- Headers beta capturados:
  - `prompt-caching-scope-2026-01-05`: presente; a semântica (isolar escopos de cache entre sessões e agentes) não foi verificada.
  - `extended-cache-ttl-2025-04-11`: Estende o tempo de retenção do cache para 1 hora.
  - `context-management-2025-06-27`: acompanha `context_management.edits = [{"type": "clear_thinking_20251015", "keep": "all"}]`; com `keep: all` nenhum pensamento é limpo, então o efeito de liberar espaço na janela não foi observado.
  - Também presentes nos 16 requests: `claude-code-20250219`, `oauth-2025-04-20`, `interleaved-thinking-2025-05-14`, `thinking-token-count-2026-05-13`, `mid-conversation-system-2026-04-07` (mensagens `role: system` em `messages`), `advisor-tool-2026-03-01`, `effort-2025-11-24`. `mid-conversation-tool-changes-2026-07-01` **não** foi enviado.

---

### 3.4 Desmistificando o "Effort: High" na Prática

O que realmente muda quando selecionamos `effort: high` nos dois ecossistemas?

```
+-----------------------------------------------------------------------------------------------+
| Característica         | Anthropic Claude (Sonnet)         | OpenAI Codex (GPT-6 Luna)        |
+-----------------------------------------------------------------------------------------------+
| Parâmetro de API       | thinking adaptive/omitted + output_config.effort high | (relatado) reasoning_effort high |
| Headers de Beta        | effort-2025-11-24, interleaved-thinking, thinking-token-count | não capturado |
| Formato de Resposta    | Blocos thinking com texto vazio + assinatura | Tokens internos (relato) |
| Consumo de Tokens      | não medido (capturas sem `usage`) | relatado ~1.200→~22.000; não verificável nas capturas |
| Impacto de Latência    | não medido (sem linha de base; tempos incluem retry) | não medido |
+-----------------------------------------------------------------------------------------------+
```

1. **No Claude:**
   - O `effort: high` vai em `output_config.effort` e acompanha `thinking: adaptive`: o modelo decide quanto pensar. Não é o Extended Thinking com `budget_tokens`.
   - O modelo pensa antes de agir, mas com `display: omitted` os blocos `thinking` voltam **vazios**, só com a assinatura (1.096 a 7.604 caracteres nas voltas seguidas da tarefa 02). Se o comprimento da assinatura acompanha o raciocínio é hipótese.
2. **No Codex:**
   - O campo `model_reasoning_effort = "high"` (passado por linha de comando; o request de inferência não foi capturado) faria o modelo alocar milhares de **Reasoning Tokens** *(relato, não verificável nas capturas)*.
   - No enigma lógico testado (Tarefa 04), segundo a resposta final do Codex, o modelo analisou sistematicamente todas as 6 permutações das três chaves e três agentes, descartando as 5 incompatíveis antes de emitir a dedução correta em um único parágrafo conciso.

---

## 4. Lições Aplicadas ao Nosso Laboratório (`graph-engineering-lab`)

A engenharia reversa destes harnesses consolida o projeto de nossos próprios agentes em LangGraph:

1. **Por que o MITM é superior ao Subprocess CLI:**
   - Chamar o binário do CLI via subprocess (`claude -p` / `codex exec`) faz cada request carregar ~330–359 KB (87–88% deles schemas de ~165–183 ferramentas, mais `gitStatus` e `AGENTS.md`) que pertencem ao fluxo de terminal humano. **Medido:** o peso. **Hipótese não testada:** que isso degrade o foco ou a acurácia do modelo.
   - O nosso proxy autenticado ([`src/subscription_proxy.py`](../src/subscription_proxy.py)) captura as credenciais e acessa a API pura sem o peso morto do harness.
2. **Arquitetura de Dois DeepAgents (Memória vs Execução):**
   - Hipótese, não medida: o Codex e o Claude sofreriam com sobrecarga de atenção quando tentam ser arquitetos de memória e executores de ferramentas ao mesmo tempo.
   - No nosso [`src/02-deepagents-experiment/deep_agents_graph.py`](../src/02-deepagents-experiment/deep_agents_graph.py), a separação em:
     - **DeepAgent 1 (Memória & Ontologia):** Construtor de diretivas e refletor epistêmico.
     - **DeepAgent 2 (Execução):** Operador de subagentes especializados (`calculate`, `python_eval`, etc.).
   é proposta para produzir um raciocínio mais nítido e rastreável; não há comparação medida com um agente único.
3. **Progressive Disclosure de Ferramentas:**
   - No grafo de `deepagents_self_improving.py`, as tools do executor são disparadas por palavra-chave no texto do pedido (`os`, `system`, `graphrag`…); o campo `required_actions` da diretiva não as restringe.

---

## 5. Replicação da Memória Persistente e Auto-Revisão (`deepagents_self_improving.py`)

A partir dos achados da engenharia reversa do Auto-Memory do Claude e da consolidação em SQLite do Codex, desenvolvemos a engine de autoaperfeiçoamento do projeto:
- **Motor de Memória (`memory_system.py`)**: Implementa o índice mestre `MEMORY.md` com arquivos `<slug>.md` estruturados em YAML frontmatter (tipos: `user`, `feedback`, `project`, `reference`), com links `[[...]]` no corpo (unidirecionais) e recuperação pela sobreposição de palavras do pedido com a linha do índice (top-3, sem limiar).
- **Catálogo de Skills Diferidas (`deferred_skills.py`)**: Expõe apenas resumos leves no prompt de planejamento; carrega o corpo de `SKILL.md` exclusivamente no momento da execução (`load_skill`). O gatilho é substring no pedido (`os` casa dentro de `nosso`).
- **Logs Estruturados & Auto-Revisão (Crítica Epistêmica)**: Cada passo de subagente é registrado com `step`, `tool`, `duration_ms` e `status`. O DeepAgent 1 executa uma auto-revisão (LLM) contra o contrato da diretiva e as memórias de feedback antes de sintetizar a resposta final. O veredito não bloqueia nada (o grafo tem 0 arestas condicionais) e, com chaves `{}` e JSON inválido na saída do modelo, o nó devolve `is_accurate: true` (0,95).
- **Validação Empírica em 2 Turnos**: observado em 1 execução, 1 regra, 2 turnos: o agente grava a regra no Turno 1 e, no Turno 2, sem menção do usuário, a carrega e cumpre a diretriz. **Limites:** o índice tinha 1 memória e `top_k = 3` sem limiar (qualquer consulta a carrega); o gatilho de escrita é uma lista de 11 substrings e grava a mensagem inteira do usuário. Prova o encanamento, não o recall seletivo.

Estudo completo e arquitetura detalhada em:  
👉 [**`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`**](../src/03-harness-reverse-experiment/memory_and_self_improvement_study.md)

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

