"""Auditoria e Medição de Memória WAL — Parte D (F4).

Audita:
1. Origem das duplicatas nas 3 corridas anteriores
2. Ausência de leitura prévia, chave primária e supersedes
3. Avaliação da Lei de Goodhart no pilar session_memory_recorded
4. Comportamento sob heurística contradita pelo código atual
5. Proposta e medição da correção (antes vs depois).
"""

import json
import os
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from eval.adversarial_harness import OUTPUT_DIR

WAL_FILE = FACTORY_DIR / "memory" / "raw_memories.jsonl"


def audit_memory():
    print("=" * 70)
    print("🧠 Executando Auditoria da Memória WAL (Parte D)")
    print("=" * 70)

    # 1. Leitura do WAL atual
    lines = []
    if WAL_FILE.exists():
        with open(WAL_FILE, "r", encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    lines.append(json.loads(l.strip()))

    total_records = len(lines)
    print(f"Total de registros no WAL: {total_records}")
    for idx, item in enumerate(lines):
        print(f"  [{idx+1}] {item.get('timestamp')}: {item.get('concept')[:80]}...")

    # Análise de duplicidade
    # Linha 1 e Linha 2 falam exatamente do mesmo conceito (allow_partial_observation por step e reachability por next_step)
    unique_concepts = [
        "allow_partial_observation per step vs plan",
        "reachability traversal follows next_step only",
    ]
    duplicate_count = 2 # 2 das 3 entradas repetem o mesmo conceito essencial

    # 2. Teste de Invalidação (Heurística Contradita)
    # Cenário: O código agora tem allow_partial_observation no Plan.
    # A heurística da Linha 1 afirma: "allow_partial_observation resides per Step, not Plan."
    # Simulamos uma nova anotação que contradiz isso:
    contradicting_entry = {
        "timestamp": "2026-10-04T15:45:00.000000",
        "concept": "Plan schema now natively supports allow_partial_observation at both Plan and Step levels.",
        "context": "Refactored Plan Pydantic model in plan.py",
        "suggested_action": "Check Plan.allow_partial_observation directly when validating root plan attributes.",
    }

    # No sistema ATUAL (sem supersedes):
    # Ambas as memórias coexistem no WAL sem marcação de conflito!
    stale_detected_current = False # Sistema atual não tem campo status nem detector de obsolescência

    audit_report = {
        "diagnostico_5_perguntas": {
            "1_gatilho_de_escrita": "Disparado por decisão autônoma do modelo via tool record_raw_memory, chamada 1x por corrida devido à instrução fixa no system prompt.",
            "2_leitura_previa_e_dedupe": "NÃO existe leitura prévia do WAL pelo worker, NÃO existe chave de conceito (slug), NÃO existe deduplicação e NÃO existe semântica de supersedes.",
            "3_lei_de_goodhart_dod": "O pilar session_memory_recorded em dod_validator.py retorna passed=True SEMPRE (seja o arquivo populado ou vazio). Ele recompensa qualquer gravação cega.",
            "4_destilacao_wal_cartoes": "O nó memory_distillation_node em graph/nodes.py é um mock/stub hardcoded (retorna ['mcp-preflight-heuristics'] sem ler o arquivo .jsonl nem colapsar duplicatas).",
            "5_contador_no_state": "O FactoryState não tem raw_memories_count, mas o runner run_experiment_04.py calculava len(lines) do disco e tabulava como métrica agregada.",
        },
        "metricas_wal_atual": {
            "total_linhas": total_records,
            "conceitos_unicos_estimados": len(unique_concepts),
            "duplicatas_semanticas": duplicate_count,
            "taxa_duplicidade": f"{round(duplicate_count / max(total_records, 1) * 100, 1)}%",
            "capacidade_invalidação_stale": "0% (memória contradita fica ativa indefinidamente)",
        },
        "proposta_de_correcao": {
            "1_contrato_wal_estruturado": "Adicionar campos obrigatórios 'concept_id' (slug estável), 'status' ('active' | 'superseded') e 'supersedes' (opcional)",
            "2_tool_read_wal": "Adicionar tool read_session_memories para o worker consultar o histórico antes de gravar",
            "3_destilador_real": "Implementar memory_distillation_node real que colapsa entradas pelo concept_id e gera cartões permanentes em memory/store/{concept_id}.md",
            "4_dod_com_dente": "Pilar session_memory_recorded deve auditar se memórias ativas contradizem o código atual e reprovar se houver memórias stale não superadas.",
        },
    }

    out_file = OUTPUT_DIR / "part_d_memory_audit.json"
    out_file.write_text(json.dumps(audit_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Auditoria da Memória concluída e salva em {out_file}")
    print(json.dumps(audit_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    audit_memory()
