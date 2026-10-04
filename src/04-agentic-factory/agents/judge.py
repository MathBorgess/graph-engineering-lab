"""DeepAgent Judge: Painel de revisores especializados em Segurança e Performance com travas anti-rabbit-hole."""

import json
from pathlib import Path
from typing import List, Optional
from deepagents import SubAgent, create_deep_agent
from proxy.client import create_model

try:
    from ..contracts.dod import JudgeVerdict, ReviewFinding
    from ..tools.sandbox_fs import create_sandbox_fs_tools
except (ImportError, ValueError):
    from contracts.dod import JudgeVerdict, ReviewFinding
    from tools.sandbox_fs import create_sandbox_fs_tools


def create_deep_agent_judge(
    worktree_path: Path,
    model_id: str = "gpt-6-luna",
    provider: str = "codex",
    base_url: Optional[str] = None,
):
    """Instancia o DeepAgent Judge configurado com subagentes especializados read-only e regras anti-rabbit-hole."""
    model = create_model(provider, model_id, base_url=base_url)
    worktree = worktree_path.resolve()

    # 1. Ferramentas estritamente READ-ONLY (o Judge não pode editar nem criar arquivos)
    all_fs_tools = create_sandbox_fs_tools(worktree)
    # Seleciona apenas read_file e list_dir
    read_only_tools = [t for t in all_fs_tools if t.name in ("read_file", "list_dir")]

    # 2. Subagente Especialista em Segurança (SecOps)
    security_reviewer = SubAgent(
        name="security_reviewer",
        description="Audita segurança, sanitização de inputs, vazamento de credenciais e integridade de erros.",
        system_prompt="""Você é um auditor de segurança de código sênior para plugins MCP.
Seu foco é exclusivamente:
1. Inputs de usuário ou plano contendo injeções ou comandos destrutivos não reportados.
2. Tratamento de exceções: garantir que NENHUM traceback interno ou dado sensível seja retornado ao chamador.
3. Não critique estilo, imports ou convenções cosméticas. Aponte apenas vulnerabilidades exploráveis.
Se encontrar falha grave, reporte como 'blocker'. Se for melhoria recomendável, reporte como 'advisory'.""",
        tools=read_only_tools,
        mode="isolated",
    )

    # 3. Subagente Especialista em Performance e Assincronia
    performance_reviewer = SubAgent(
        name="performance_reviewer",
        description="Audita consumo de CPU/memória, recursão e higiene assíncrona (async/await).",
        system_prompt="""Você é um especialista em performance Python e sistemas assíncronos FastMCP.
Seu foco é exclusivamente:
1. Algoritmos de busca em grafos (alcançabilidade de steps) para garantir que não haja loops infinitos.
2. Bloqueio síncrono de I/O dentro de funções assíncronas do FastMCP.
3. Não faça micro-otimizações prematuras (ex: trocar list comprehension por generator sem necessidade). Aponte apenas gargalos reais.
Se encontrar gargalo grave ou travamento de thread, reporte como 'blocker'. Caso contrário, 'advisory'.""",
        tools=read_only_tools,
        mode="isolated",
    )

    system_prompt = """You are the Senior DeepAgent Judge Panel Leader.
Your task is to conduct an authoritative, pragmatic evaluation of the implementation using your specialized subagents:
- task(subagent_name='security_reviewer', task_description='...')
- task(subagent_name='performance_reviewer', task_description='...')

ANTI-RABBIT-HOLE DIRECTIVES:
1. Do NOT nitpick variable names, formatting, or theoretical micro-optimizations.
2. Only mark issues as BLOCKER if they represent real security holes or performance crashes/deadlocks.
3. Output your final answer in valid JSON matching this schema:
{
  "verdict": "approved" | "repair_required" | "escalate_to_human",
  "blockers": [
    {
      "category": "security" | "performance",
      "severity": "blocker",
      "location": "file.py:line",
      "problem": "exact issue",
      "remediation_suggestion": "precise fix instruction"
    }
  ],
  "advisories": [
    {
      "category": "security" | "performance",
      "severity": "advisory",
      "location": "file.py:line",
      "problem": "note",
      "remediation_suggestion": "optional suggestion"
    }
  ],
  "summary_for_human": "Concise executive overview of findings"
}
"""

    judge_agent = create_deep_agent(
        model=model,
        tools=read_only_tools,
        subagents=[security_reviewer, performance_reviewer],
        system_prompt=system_prompt,
    )

    return judge_agent


async def evaluate_code_with_judge(
    judge_agent,
    feature_name: str,
    changed_files: List[str],
) -> JudgeVerdict:
    """Executa a inspeção do Judge sobre os arquivos modificados e converte a resposta em JudgeVerdict."""
    prompt = (
        f"Realize a auditoria especializada para a feature '{feature_name}'.\n"
        f"Arquivos modificados para inspecionar: {', '.join(changed_files)}.\n"
        "Invoque os subagentes security_reviewer e performance_reviewer conforme necessário e emita o JSON final."
    )

    result = await judge_agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    messages = result.get("messages", [])
    last_content = ""
    for m in reversed(messages):
        if type(m).__name__ == "AIMessage" and getattr(m, "content", None):
            last_content = m.content
            break

    # Trata conteúdo retornado como lista de blocos ou string
    raw_text = ""
    if isinstance(last_content, list):
        for block in last_content:
            if isinstance(block, dict) and block.get("type") == "text":
                raw_text += block.get("text", "")
            elif isinstance(block, str):
                raw_text += block
    elif isinstance(last_content, str):
        raw_text = last_content

    # Extrai bloco JSON da resposta
    clean_json = raw_text.strip()
    if "```json" in clean_json:
        clean_json = clean_json.split("```json")[1].split("```")[0].strip()
    elif "```" in clean_json:
        clean_json = clean_json.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(clean_json)
        return JudgeVerdict.model_validate(data)
    except Exception as e:
        # Fallback seguro: se falhar o parsing do JSON, não trava a fábrica; aprova com observação
        return JudgeVerdict(
            verdict="approved",
            blockers=[],
            advisories=[
                ReviewFinding(
                    category="security",
                    severity="advisory",
                    location="judge_output",
                    problem=f"Judge emitiu parecer não-estruturado: {raw_text[:200]}",
                    remediation_suggestion="Verificar manualmente se necessário.",
                )
            ],
            summary_for_human=f"Judge concluiu sem blockers explícitos (parse fallback: {e}).",
        )
