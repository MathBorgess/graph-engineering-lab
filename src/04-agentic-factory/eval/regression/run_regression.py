"""Suíte de Regressão da Fábrica de Software Agêntica (Experimento 04 - Rodada 3).

Roda com um único comando e avalia:
- Canários de Esteira (Controle Limpo + 5 violações plantadas)
- Bateria A (A-1 a A-8, A-9 com oráculo spec, A-10)
- Bateria I (I-1 a I-7 integridade da suíte de testes O5)
- Casos G do Juiz com Prova O7 (G-1 a G-6)

Imprime a taxa de veto com numerador e denominador exatos.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

FACTORY_DIR = Path(__file__).resolve().parent.parent.parent
LAB_ROOT = FACTORY_DIR.parent
ROUND3_DIR = FACTORY_DIR / "eval" / "round3"

if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from eval.canary_harness import run_canaries, run_battery_a


def run_full_regression() -> Dict[str, Any]:
    print("=" * 75)
    print("🛡️ EXECUTANDO SUÍTE COMPLETA DE REGRESSÃO DA FÁBRICA AGÊNTICA")
    print("=" * 75)

    start_time = time.time()
    
    # 1. Executa Canários
    print("\n▶ [1/4] Executando Bateria de Canários...")
    canary_results = run_canaries()
    clean_passed = canary_results["canary_0_clean_control"]["is_valid"] and not canary_results["canary_0_clean_control"]["vetoed"]
    planted_caught = sum(
        1 for k, v in canary_results.items()
        if k != "canary_0_clean_control" and (v.get("vetoed") or not v.get("is_valid"))
    )
    canaries_total = len(canary_results) - 1

    # 2. Executa Bateria A
    print("\n▶ [2/4] Executando Bateria A (10 Mutações Adversariais)...")
    battery_a_results = run_battery_a()
    a_vetoed = sum(1 for v in battery_a_results.values() if v.get("vetoed"))
    a_total = len(battery_a_results)

    # 3. Carrega Bateria I (Integridade da Suíte O5)
    print("\n▶ [3/4] Avaliando Bateria I (7 Casos de Integridade da Suíte O5)...")
    i_cases_dir = ROUND3_DIR
    i_files = sorted(list(i_cases_dir.glob("case_i*.json")))
    i_vetoed = 0
    for f in i_files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("vetoed"):
                i_vetoed += 1
        except Exception:
            pass
    i_total = len(i_files)

    # 4. Carrega Gabarito do Juiz com Prova O7 (Casos G)
    print("\n▶ [4/4] Avaliando Gabarito do Juiz com Prova O7 (6 Casos)...")
    judge_res_path = ROUND3_DIR / "judge_benchmark_results.json"
    g_vetoed = 0
    g_total = 6
    if judge_res_path.exists():
        j_data = json.loads(judge_res_path.read_text(encoding="utf-8"))
        g_vetoed = j_data["sonnet_5_5"]["true_positives"]
        g_total = j_data["benchmark_cases_count"]

    elapsed_s = round(time.time() - start_time, 2)

    total_adversarial_tested = a_total + i_total + 3  # 3 blockers reais em G
    total_adversarial_caught = a_vetoed + i_vetoed + g_vetoed
    
    veto_rate_pct = round((total_adversarial_caught / total_adversarial_tested) * 100, 1) if total_adversarial_tested > 0 else 0.0

    print("\n" + "=" * 75)
    print("📊 SCORECARD CONSOLIDADO DA REGRESSÃO")
    print("=" * 75)
    print(f"Controle Limpo: {'PASS' if clean_passed else 'FAIL'}")
    print(f"Canários Plantados Barrados: {planted_caught}/{canaries_total} ({round((planted_caught/canaries_total)*100, 1)}%)")
    print(f"Bateria A (Mutações Comportamentais): {a_vetoed}/{a_total} vetadas ({round((a_vetoed/a_total)*100, 1)}%)")
    print(f"Bateria I (Integridade O5): {i_vetoed}/{i_total} vetadas ({round((i_vetoed/i_total)*100, 1)}%)")
    print(f"Gabarito Juiz O7 (Blockers Reais com Prova): {g_vetoed}/3 confirmadas ({round((g_vetoed/3)*100, 1)}%)")
    print("-" * 75)
    print(f"🎯 TAXA DE VETO CONSOLIDADA: {total_adversarial_caught}/{total_adversarial_tested} ({veto_rate_pct}%)")
    print(f"⏱️ Tempo total de regressão: {elapsed_s}s")
    print("=" * 75)

    regression_summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "clean_control_passed": clean_passed,
        "planted_canaries": f"{planted_caught}/{canaries_total}",
        "battery_a": f"{a_vetoed}/{a_total}",
        "battery_i": f"{i_vetoed}/{i_total}",
        "judge_o7_blockers": f"{g_vetoed}/3",
        "consolidated_veto_rate": f"{total_adversarial_caught}/{total_adversarial_tested}",
        "consolidated_veto_pct": veto_rate_pct,
        "elapsed_seconds": elapsed_s,
    }

    (ROUND3_DIR / "regression_summary.json").write_text(
        json.dumps(regression_summary, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    return regression_summary


if __name__ == "__main__":
    run_full_regression()
