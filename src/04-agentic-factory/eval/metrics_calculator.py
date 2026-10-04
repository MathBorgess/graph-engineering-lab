"""Cálculo rigoroso das 6 métricas de eficácia agêntica com numeradores e denominadores."""

from typing import Any, Dict


def compute_rigorous_metrics(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula as 6 métricas com numeradores, denominadores e 'não exercitado'."""
    # 1. Veto Rate dos Validadores
    semente_bugs = raw_data.get("injected_bugs_count", 0)
    bugs_vetados = raw_data.get("validator_failures_detected", 0)
    if semente_bugs > 0:
        veto_rate = f"{bugs_vetados}/{semente_bugs} ({round(bugs_vetados / semente_bugs * 100, 1)}% de falhas barradas)"
    else:
        veto_rate = "não exercitado (0 defeitos semeados na corrida limpa)"

    # 2. Eficácia Anti-Rabbit-Hole do Juiz
    total_findings = raw_data.get("judge_findings_total", 0)
    blockers_reais = raw_data.get("judge_blockers_count", 0)
    judge_cycles = raw_data.get("judge_cycles", 0)
    if total_findings > 0:
        pertinencia = f"{blockers_reais}/{total_findings} blockers pertinentes ({round(blockers_reais / total_findings * 100, 1)}%) | Ciclos: {judge_cycles}/1"
    else:
        pertinencia = f"não exercitado (0 apontamentos do judge) | Ciclos: {judge_cycles}/1"

    # 3. Sinal/Ruído do HITL (Intervention Signal Ratio)
    total_hitl = raw_data.get("hitl_interrupts_total", 0)
    justified_hitl = raw_data.get("hitl_interrupts_justified", 0)
    if total_hitl > 0:
        hitl_signal = f"{justified_hitl}/{total_hitl} ({round(justified_hitl / total_hitl * 100, 1)}% de paradas em marcos reais)"
    else:
        hitl_signal = "não exercitado (0 interrupções disparadas)"

    # 4. Frugalidade de Contexto
    compact_chars = raw_data.get("compact_catalog_chars", 365)
    full_chars = raw_data.get("full_catalog_chars", 2652)
    saved_chars = full_chars - compact_chars
    pct_saved = round(saved_chars / full_chars * 100, 1)
    context_frugality = f"{compact_chars} chars vs {full_chars} chars ({saved_chars} chars / {pct_saved}% de economia por request)"

    # 5. Taxa de Invalidação / Higiene de Memória (Anti-Stale)
    total_wal = raw_data.get("raw_memories_count", 0)
    dupes = raw_data.get("semantic_duplicates", 0)
    if total_wal > 0:
        anti_stale = f"{total_wal - dupes}/{total_wal} conceitos únicos ({round(dupes / total_wal * 100, 1)}% duplicatas)"
    else:
        anti_stale = "não exercitado (WAL vazio)"

    # 6. Taxa de Convergência de Reparo (MTTR Agêntico)
    attempts = raw_data.get("worker_attempts", 1)
    max_att = raw_data.get("max_attempts", 3)
    mttr = f"{attempts}/{max_att} tentativas gastas para atingir DoD verde"

    return {
        "1_veto_rate": veto_rate,
        "2_anti_rabbit_hole": pertinencia,
        "3_hitl_signal_ratio": hitl_signal,
        "4_context_frugality": context_frugality,
        "5_anti_stale_memory": anti_stale,
        "6_mttr_convergence": mttr,
        "raw_data": raw_data,
    }
