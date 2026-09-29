# 🧠 Estudo Aprofundado: Geração e Carga de Memória, Context Deferred e Auto-Revisão em DeepAgents

**Autor:** Matheus Borges  
**Repositório:** `graph-engineering-lab`  
**Experimento:** `src/03-harness-reverse-experiment`  
**Data:** Setembro de 2026  
**Status:** Implementado, Validado em 2 Turnos e Funcional  

---

## 📌 Sumário Executivo

Este documento disseca a engenharia reversa de dois dos mecanismos mais sofisticados presentes no **Claude Code CLI** e no **OpenAI Codex CLI**:
1. **Geração e Carregamento de Memória Persistente** (como o modelo aprende preferências e regras de projeto entre turnos).
2. **Context Deferred & Progressive Disclosure** (como evitar o inchaço de contexto sem perder acesso a dezenas de ferramentas e skills).
3. **Replicação Arquitetural em DeepAgents (LangGraph)** com:
   - Um índice mestre `MEMORY.md` e arquivos estruturados `<slug>.md` com YAML frontmatter.
   - Um catálogo diferido de skills com carregamento sob demanda (`load_skill`).
   - Um subsistema de **Logs Estruturados de Ação**.
   - Um nó de **Auto-Revisão (Crítica Epistêmica)** que audita a execução antes da resposta ao usuário.
   - Um fluxo contínuo de **Self-Improvement** que consolida novas memórias e expande a ontologia.

---

## 1. Como a Memória de Usuário é Gerada e Carregada no Claude Code e Codex

### 1.1 No Claude Code CLI (Sistema de Auto-Memory)
A análise dos payloads de 474 KB capturados pelo nosso proxy MITM revelou o protocolo exato da Anthropic para persistência:

```
~/.claude/projects/<project-slug>/memory/
├── MEMORY.md                 <--- Master Index (Injetado em TODOS os turnos, < 200 linhas)
├── feedback-db-rules.md      <--- Specialized Memory File
├── user-profile.md           <--- Specialized Memory File
└── project-deadlines.md      <--- Specialized Memory File
```

#### A. Estrutura Canônica de cada Arquivo de Memória (`<slug>.md`)
```markdown
---
name: short-kebab-case-slug
description: one-line summary used to decide relevance in future conversations
metadata:
  type: user | feedback | project | reference
---

[Regra, Preferência ou Fato Aprendido]

**Why:** [Motivação ou incidente que originou a regra]
**How to apply:** [Condições e escopo de ativação]

**Related:** [[outro-slug]]
```

#### B. Os 4 Tipos Canônicos de Memória:
1. **`user`**: Perfil técnico, experiência, linguagem preferida, papel na equipe.
2. **`feedback`**: Correções explícitas (*"não use mocks aqui"*) ou confirmações silenciosas (*"essa abordagem agrupada foi perfeita"*).
3. **`project`**: Decisões de negócio não deriváveis do código (ex: congelamento de branch, migrações de compliance).
4. **`reference`**: Ponteiros para sistemas externos (tickets no Linear, dashboards no Grafana).

#### C. Regras de Exclusão Estritas ("O que NÃO salvar"):
- O harness proíbe categoricamente salvar padrões de código que já existem nos arquivos, histórico de git (`git log` é autoritativo) ou passos efêmeros de debugging da conversa atual.

#### D. Mecanismo de Carregamento (Progressive Disclosure de Memória):
- O agente não lê todas as memórias. Ele recebe apenas o índice de 1 linha de cada entrada em `MEMORY.md`.
- Se uma instrução ou tarefa corresponder a uma entrada do índice, o agente usa a ferramenta `Read` para abrir especificamente o arquivo `<slug>.md` correspondente.

---

### 1.2 No OpenAI Codex CLI (Sistema de Consolidação em Duas Fases)
A engenharia reversa do executável `codex` e dos arquivos em `~/.codex` revelou uma arquitetura dual:
1. **Camada 1: SQLite + Logs Episódicos (`memories_1.sqlite` e `raw_memories.md`)**:
   - Cada turno, comando e observação de ferramenta é registrado imediatamente como evento de telemetria e histórico bruto.
2. **Camada 2: Memory Consolidation Agent (Phase 2 Heartbeat)**:
   - Identificamos nos binários do Codex o processo do **Agente de Consolidação de Memória** (`memory consolidation agent`):
     - Opera em segundo plano ou no fechamento da sessão.
     - Lê os logs brutos episódicos e destila padrões duradouros para `memory_summary.md`.
     - Evita que o modelo gaste tempo de inferência ou tokens durante o turno interativo imediato do usuário.

---

### 1.3 A Matriz de Decisão Epistêmica: Como o Agente SABE Quando Escrever, Atualizar ou Deletar uma Memória

Uma das dúvidas centrais em sistemas agênticos avançados é: **qual é o mecanismo cognitivo exato que faz o agente decidir entre apenas responder ao usuário ou abrir ferramentas de persistência de memória (`Write`/`Edit`)?**

A análise dos system prompts capturados pelo nosso proxy MITM revela que isso não é mágica estatística imprevisível, mas sim um **conjunto rígido de heurísticas condicionais, sinais de turno, regras de exclusão estritas e contratos de verificação da verdade**.

#### A. O Fluxo de Decisão Cognitiva a Cada Turno

```mermaid
flowchart TD
    Input([Input do Usuário ou Resultado de Execução]) --> CheckExplicit{Houve comando explícito?\n'Lembre-se', 'Esqueça', 'Guarde como regra'}
    
    CheckExplicit -- Sim: Lembrar --> SelectType[Classificar Tipo:\nuser, feedback, project, reference]
    CheckExplicit -- Sim: Esquecer --> DeleteMem[Localizar no MEMORY.md\ne Deletar arquivo <slug>.md]
    
    CheckExplicit -- Não --> CheckImplicit{Houve sinal implícito?\n• Correção/Atrito ('não faça isso')\n• Confirmação ('perfeito, manter assim')\n• Perfil do usuário revelado\n• Decisão de negócio / data limite}
    
    CheckImplicit -- Não --> NoMemory[Não mutar memória.\nSeguir fluxo normal de resposta.]
    CheckImplicit -- Sim --> EvalNegative{Viola Negative Boundary?\n• É derivável do código no disco?\n• Está no git log / blame?\n• Já está no CLAUDE.md / AGENTS.md?\n• É efêmero desta sessão/tarefa?}
    
    EvalNegative -- Sim --> Discard[Descartar salvamento.\n(Se o usuário insistir, extrair apenas o não-óbvio)]
    EvalNegative -- Não --> SelectType
    
    SelectType --> CheckExisting{Já existe registro similar\nno índice MEMORY.md?}
    
    CheckExisting -- Sim --> EditExisting["Atualizar Memória Existente (Edit <slug>.md)\n• Refinar regra ou adicionar novo Why / How to apply\n• Evitar arquivos duplicados"]
    CheckExisting -- Não --> CreateNew["Criar Nova Memória (Write <slug>.md)\n1. Gravar arquivo com YAML frontmatter\n2. Adicionar linha de índice no MEMORY.md (<150 chars)"]
    
    EditExisting --> VerifyStale[Verificar se observações atuais contradizem memórias antigas]
    CreateNew --> VerifyStale
    VerifyStale --> Finalize[Memória Sincronizada e Ativa]
```

#### B. Os Gatilhos Explícitos e Implícitos de Escrita

O harness ensina o modelo a monitorar continuamente 5 classes de sinais conversacionais:

| Tipo de Gatilho | Padrões Verbais e Sinais Observados | Tipo de Memória Alvo | Exemplo Prático Capturado nos Payloads | Ação Executada pelo Agente |
| :--- | :--- | :--- | :--- | :--- |
| **Comando Explícito** | *"Lembre-se de...", "Grave isso...", "Guarde como regra...", "Never forget..."* | Qualquer (o que melhor se adequar) | Usuário: *"Lembre-se de sempre formatar saídas matemáticas em MB e KB."* | Escreve imediatamente em `<slug>.md` e indexa em `MEMORY.md`. |
| **Feedback de Correção (Negativo)** | *"Não faça isso", "Não use mocks", "Pare de resumir no final", "Você errou a biblioteca"* | `feedback` | Usuário: *"Não mocke o banco nesses testes — ano passado mocks mascararam falha de migração."* | Extrai a regra (*"banco real obrigatório"*), o **Why:** (*incidente anterior*) e **How to apply:** (*testes de integração*). |
| **Feedback de Confirmação (Positivo Silencioso)** | *"Sim, exatamente", "Perfeito, manter tudo agrupado foi a decisão certa", aceitar escolha não-trivial sem atrito* | `feedback` | Usuário: *"Sim, fazer um único PR agrupado foi a decisão certa aqui."* | Grava a confirmação para evitar que o modelo se torne excessivamente cauteloso ou reverta decisões válidas. |
| **Revelação de Perfil do Usuário** | *"Sou cientista de dados...", "Tenho 10 anos de Go, mas é meu primeiro contato com React..."* | `user` | Usuário explicando seu background técnico durante uma dúvida. | Grava o perfil para calibrar analogias conceituais (ex: explicar React usando conceitos de concorrência em Go). |
| **Restrições de Projeto / Negócio** | *"Vamos congelar merges quinta-feira", "A reescrita de auth é por exigência da auditoria legal"* | `project` | Menção a prazos, incidentes, sprints ou motivações corporativas. | **Regra Obrigatória:** Converte datas relativas em absolutas (ex: *"quinta-feira"* $\to$ `2026-03-05`) e grava a motivação. |
| **Ponteiros de Ecossistema Externo** | *"Os bugs ficam na fila INGEST do Linear", "O dashboard do oncall é grafana.internal/latency"* | `reference` | Menção a links, boards, canais do Slack ou métricas externas. | Salva ponteiro para saber onde buscar contexto em turnos futuros. |

#### C. O Filtro de Rejeição (Negative Boundary: O que NUNCA Salvar)

O agente **NÃO salva qualquer observação**. O harness impõe uma fronteira negativa rígida com 5 exclusões inegociáveis:
1. **Código e Arquitetura do Repositório**: Se o modelo pode descobrir rodando `grep`, `find` ou lendo arquivos do projeto, **é expressamente proibido salvar em memória**.
2. **Histórico do Git**: `git log` e `git blame` são as fontes autoritativas da verdade. Memória não deve resumir quem comitou o quê ou quando.
3. **Soluções de Bugs ou Receitas de Fix**: O conserto pertence ao código e à mensagem de commit. A memória só deve ser criada se o usuário manifestou uma preferência duradoura de como abordar problemas futuros.
4. **Instruções já Documentadas**: O que já consta em `CLAUDE.md`, `AGENTS.md` ou regras do repositório nunca deve ser duplicado na memória.
5. **Estado Efêmero de Sessão**: Se a informação serve apenas para a tarefa em andamento (ex: lista de arquivos a editar agora, progresso dos testes locais), o harness proíbe `memory` e força o uso de `Plan` ou `Tasks`.

> **Regra de Resistência à Solicitação do Usuário:** Mesmo se o usuário pedir explicitamente: *"Salve na memória um resumo do que fizemos neste PR"*, o harness instrui o modelo a questionar ou filtrar: *"O que houve de surpreendente ou não-óbvio que precisa ser mantido para além do histórico do git?"*

#### D. Heurística de Mutação: Criar vs. Atualizar vs. Invalidação de Memória Obsoleta (Stale Memory)

Como o agente sabe se deve criar um novo arquivo ou alterar um já existente?
1. **Deduplicação Proativa via Índice `MEMORY.md`**:
   - Antes de criar um arquivo novo, o agente consulta o índice `MEMORY.md` (que está sempre carregado no contexto inicial).
   - Se já existe uma entrada sobre o mesmo tópico (ex: `feedback-database-testing.md`), ele **não cria arquivo novo**. Ele emite uma chamada `Edit` no arquivo existente, adicionando novas regras ou ajustando o campo `How to apply:`, preservando o índice conciso.
2. **Princípio da Primazia da Observação Presente (Stale Memory Handling)**:
   - Uma memória reflete o que era verdade *quando foi escrita*. Ela não é um axioma eterno.
   - Antes de aplicar uma recomendação baseada em memória antiga que mencione arquivos, rotas ou parâmetros:
     - Se a memória cita um arquivo: o agente verifica se o arquivo ainda existe no disco.
     - Se cita uma função ou endpoint: roda `grep` para verificar se ainda existe.
   - **Regra de Ouro do Conflito:** Se uma memória diz *"o servidor usa JWT no header Authorization"*, mas o código no disco mostra que agora usa cookies HttpOnly com session token, **a observação atual no disco tem precedência absoluta sobre a memória**. O agente é obrigado a confiar na realidade do código e atualizar ou deletar a memória obsoleta.

#### E. Comparativo de Implementação entre os Três Sistemas

| Dimensão | Claude Code CLI (Anthropic) | OpenAI Codex CLI | DeepAgents LangGraph (`deepagents_self_improving.py`) |
| :--- | :--- | :--- | :--- |
| **Quem decide a escrita** | O próprio modelo LLM no turno interativo via tool calls (`Write`/`Edit`). | **Memory Consolidation Agent** assíncrono em segundo plano (Phase 2 heartbeat). | O nó **`auto_review`** audita logs de execução e o nó **`self_improve_and_consolidate`** persiste. |
| **Sobrecarga de Turno** | Consome tool calls e tokens no próprio turno do usuário. | Zero overhead de inferência no turno interativo (delegado ao background). | Executado de forma determinística no pipeline cíclico do grafo (Node 3 $\to$ Node 4). |
| **Estrutura de Armazenamento** | Arquivos `.md` individuais com YAML frontmatter + `MEMORY.md`. | Banco `memories_1.sqlite` bruto + `memory_summary.md` consolidado. | Arquivos `.md` individuais com frontmatter + `MEMORY.md` + Triplas no Grafo Ontológico. |
| **Garantia contra Inchaço** | Limite estrito de 200 linhas no índice `MEMORY.md` com truncamento. | Compressão periódica dos logs SQLite em sumários de alto nível. | Poda pelo índice de relevância top-k e enriquecimento semântico da ontologia. |

---

## 2. O Mecanismo de "Context Deferred" (Diferimento de Contexto)

O grande desafio de sistemas agenticos modernos é a sobrecarga de ferramentas: disponibilizar 150 ferramentas no schema JSON satura a atenção do modelo e gasta até 30% da janela com schemas não utilizados.

### Como Claude Code e Codex resolvem isso:

```
[Catálogo Leve no System Prompt / Section]
   ├─ Skill: graph-rag-optimizer (triggers: graphrag, triples)
   └─ Skill: system-profiler     (triggers: os, host, hardware)
               │
               │ (Usuário menciona "GraphRAG")
               ▼
[Gatilho Ativado pelo Planejador]
               │
               ▼
[Carregamento On-Demand via load_skill / Read]
  --> Carrega o corpo de SKILL.md apenas no Turno de Execução
```

- **No Claude Code:** O prompt inclui uma tabela textual com os nomes das skills e blocos `TRIGGER / SKIP`. Quando o gatilho bate, o modelo invoca `Skill(skill="...")`.
- **No Codex:** O prompt inclui a seção `## Skills` com nomes, descrições resumidas (com orçamento de tokens dinâmico) e aliases de raiz (`r0`). O agente principal é estritamente obrigado a abrir e ler o `SKILL.md` antes de tomar ações.

---

## 3. Replicando a Arquitetura em DeepAgents (`deepagents_self_improving.py`)

No nosso laboratório, replicamos essa arquitetura completa em um grafo cíclico de 4 nós em LangGraph:

```mermaid
flowchart TD
    START([START]) --> Plan["🧠 Node 1: Plan & Recall\n• Lê índice MEMORY.md\n• Carrega apenas memórias relevantes\n• Avalia gatilhos de Skills Deferred\n• Gera Contrato de Diretiva"]
    Plan --> Exec["⚙️ Node 2: Execution & Structured Logs\n• Carrega SKILL.md on-demand (Context Deferred)\n• Executa ferramentas dos subagentes\n• Registra logs com latência e status"]
    Exec --> Review["🔍 Node 3: Auto-Revisão (Epistemic Critique)\n• Audita execution_logs contra a Diretiva\n• Verifica compliance com regras de feedback\n• Atribui score de confiança e detecta falhas"]
    Review --> Consolidate["🚀 Node 4: Self-Improvement & Consolidation\n• Extrai novas regras -> Salva <slug>.md e MEMORY.md\n• Extrai novas entidades -> Expande Grafo Ontológico\n• Sintetiza resposta final grounded"]
    Consolidate --> END_NODE([END])
```

### 3.1 O Estado Global do Grafo (`SelfImprovingState`)
```python
class SelfImprovingState(TypedDict):
    user_goal: str
    memory_index: List[Dict[str, str]]       # Linhas do MEMORY.md
    recalled_memories: List[Dict[str, Any]]  # Slugs abertos por pertinência
    deferred_skills_catalog: List[Dict[str, Any]] # Assinaturas leves
    active_skills: List[str]                 # Skills acionadas neste turno
    loaded_skill_instructions: Dict[str, str]# Texto completo do SKILL.md carregado
    ontology: Dict[str, Any]                 # Grafo de entidades e triplas
    directive: Dict[str, Any]                # Contrato formal para o executor
    execution_logs: List[Dict[str, Any]]     # Rastreamento fino de cada chamada
    execution_result: Dict[str, Any]         # Sumário tático de execução
    auto_review: Dict[str, Any]              # Crítica epistêmica de conformidade
    memory_deltas: List[Dict[str, Any]]      # Novas memórias criadas no turno
    final_output: str                        # Resposta final apresentada
    iteration_count: int
```

---

## 4. Validação Experimental em 2 Turnos

Executamos o teste automatizado de 2 turnos com o backend Codex via nosso proxy local (`python src/03-harness-reverse-experiment/deepagents_self_improving.py --test`):

### 4.1 Turno 1: Aprendizado e Criação de Memória
- **Instrução do Usuário:**  
  *"Lembre-se que em todos os cálculos do laboratório, eu prefiro a resposta sempre em Megabytes (MB) e Kilobytes (KB). Agora use a skill de graphrag para calcular o custo de 20,000 nós e 50,000 arestas."*
- **Comportamento Observado:**
  1. O nó `plan_and_recall` identificou o gatilho da skill `graph-rag-optimizer` e a marcou como ativa.
  2. O executor disparou `load_skill("graph-rag-optimizer")`, obtendo as instruções de dimensionamento de nós (128 bytes) e arestas (96 bytes).
  3. O nó de **Auto-Revisão** detectou que uma regra duradoura havia sido declarada.
  4. O nó de **Self-Improvement** gerou o arquivo [`project_memory/pref-1790680343.md`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/project_memory/pref-1790680343.md) e registrou a entrada correspondente no [`project_memory/MEMORY.md`](file:///Users/matheusborges/github/graph-engineering-lab/src/03-harness-reverse-experiment/project_memory/MEMORY.md).

### 4.2 Turno 2: Recuperação Automática e Compliance
- **Instrução do Usuário:**  
  *"Calcule a memória necessária para 45,000 entidades adicionais no nosso grafo e inspecione nosso SO."*  
  *(Observe que o usuário **não mencionou** MB nem KB nesta rodada).*
- **Comportamento Observado:**
  1. O nó `plan_and_recall` consultou o índice `MEMORY.md`, localizou a memória de preferência `pref-1790680343` e a carregou no contexto.
  2. A diretiva impôs: *"Formatar todos os cálculos estritamente em KB e MB conforme memória de feedback ativa"*.
  3. Ambas as skills `graph-rag-optimizer` e `system-profiler` foram ativadas e lidas sob demanda via Context Deferred.
  4. A resposta final entregou o cálculo exato formatado em **KB e MB**:
     `45.000 × 1 KB = 45.000 KB ≈ 43,95 MB`, cumprindo a preferência automaticamente sem necessidade de reforço pelo usuário.

---

## 5. Como o Modelo Lida com Logs e Auto-Revisão

Um agente que apenas devolve a saída bruta de uma ferramenta corre sério risco de alucinar ou ignorar erros silenciosos. Nossa arquitetura introduz dois mecanismos:

### 5.1 Logs Estruturados de Ação
Cada chamada de ferramenta dos subagentes gera um registro imutável com carimbo de tempo:
```json
{
  "step": 1,
  "tool": "load_skill",
  "input": {"skill_name": "graph-rag-optimizer"},
  "output": {"status": "success", "size_chars": 612},
  "duration_ms": 2.14,
  "status": "success"
}
```

### 5.2 O Nó de Auto-Revisão (Crítica Epistêmica)
Antes de responder ao usuário, o DeepAgent 1 executa uma reflexão crítica contra o log:
- **Acurácia Numérica:** Os cálculos matemáticos batem com o que foi solicitado?
- **Conformidade com Memórias:** As regras registradas em `feedback` foram violadas?
- **Omissões:** Alguma ferramenta prometida na diretiva deixou de ser chamada?
- **Score de Confiança:** Emite um índice de confiança (0.0 a 1.0) e uma nota crítica que guia a redação da resposta final grounded.

---

## 6. Conclusões e Guia de Uso

A implementação demonstra que é possível atingir paridade arquitetural com os melhores harnesses comerciais (Claude Code e OpenAI Codex) utilizando LangGraph:
1. **O contexto permanece limpo** através do catálogo diferido de skills.
2. **O agente não esquece preferências** graças ao motor de arquivos `MEMORY.md` com frontmatter.
3. **O agente audita suas próprias ações** através do nó de auto-revisão de logs.

Para rodar o modo interativo e testar novos cenários de autoaperfeiçoamento:
```bash
.venv/bin/python src/03-harness-reverse-experiment/deepagents_self_improving.py
```
Para reexecutar o teste de 2 turnos:
```bash
.venv/bin/python src/03-harness-reverse-experiment/deepagents_self_improving.py --test
```
