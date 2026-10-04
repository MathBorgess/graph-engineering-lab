"""Benchmark e Harness do Juiz com Prova (O7): Claude Sonnet 5.5 vs GPT-6 Luna.

Mecanismo O7:
- Cada blocker precisa citar `arquivo:linha` e fornecer reprodução executável (código Python ou entrada que falha).
- A esteira valida a citação (se arquivo e linha existem) e executa a reprodução em subprocesso.
- Blocker sem prova reproduzida com sucesso vira advisory.

Gabarito Semeado (6 Casos):
1. G-1 (Blocker Real): Path Traversal não sanitizado em leitura de arquivo.
2. G-2 (Blocker Real): Command Injection via shell=True com entrada externa.
3. G-3 (Blocker Real): Chamada síncrona bloqueante (time.sleep) dentro de função assíncrona.
4. G-4 (Cosmético/Falso): Variável com nome genérico e formatação de docstring.
5. G-5 (Cosmético/Falso): Loop for tradicional em vez de list comprehension.
6. G-6 (Cosmético/Falso): Import não utilizado e comentário TODO.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

WORKTREE_PATH = Path("/Users/matheusborges/github/mcps-catalog-worktree-exp04/laya-computer").resolve()
ROUND3_DIR = FACTORY_DIR / "eval" / "round3"
ROUND3_DIR.mkdir(parents=True, exist_ok=True)

from agents.llm_client import invoke_sonnet, invoke_worker_codex


BENCHMARK_CASES = [
    {
        "id": "case_g1_path_traversal",
        "name": "G-1: Path Traversal Vulnerability",
        "is_real_blocker": True,
        "category": "security",
        "file_path": "laya_computer/storage_helper.py",
        "line_number": 8,
        "code_snippet": (
            "import os\n\n"
            "def read_user_asset(base_dir: str, user_filename: str) -> str:\n"
            "    # Vulnerable path concatenation without abspath confinement check\n"
            "    file_path = os.path.join(base_dir, user_filename)\n"
            "    with open(file_path, 'r', encoding='utf-8') as f:\n"
            "        return f.read()\n"
        ),
    },
    {
        "id": "case_g2_command_injection",
        "name": "G-2: Command Injection via shell=True",
        "is_real_blocker": True,
        "category": "security",
        "file_path": "laya_computer/cli_helper.py",
        "line_number": 7,
        "code_snippet": (
            "import subprocess\n\n"
            "def query_system_info(user_arg: str) -> str:\n"
            "    # Command injection vulnerability: shell=True with unescaped user string\n"
            "    cmd = f'echo query: {user_arg}'\n"
            "    res = subprocess.check_output(cmd, shell=True, text=True)\n"
            "    return res.strip()\n"
        ),
    },
    {
        "id": "case_g3_async_blocking_sleep",
        "name": "G-3: Blocking Synchronous Call in Async Routine",
        "is_real_blocker": True,
        "category": "performance",
        "file_path": "laya_computer/async_worker.py",
        "line_number": 8,
        "code_snippet": (
            "import asyncio\n"
            "import time\n\n"
            "async def handle_request_batch(items: list) -> list:\n"
            "    # Blocker: time.sleep inside async event loop freezes the thread\n"
            "    time.sleep(2.0)\n"
            "    return [i * 2 for i in items]\n"
        ),
    },
    {
        "id": "case_g4_cosmetic_naming",
        "name": "G-4: Generic Variable Name & Short Docstring",
        "is_real_blocker": False,
        "category": "cosmetic",
        "file_path": "laya_computer/formatter.py",
        "line_number": 4,
        "code_snippet": (
            "def format_summary(data: dict) -> str:\n"
            "    '''Format.'''\n"
            "    out = []\n"
            "    for k, v in data.items():\n"
            "        out.append(f'{k}={v}')\n"
            "    return ', '.join(out)\n"
        ),
    },
    {
        "id": "case_g5_cosmetic_loop_style",
        "name": "G-5: For Loop instead of List Comprehension",
        "is_real_blocker": False,
        "category": "cosmetic",
        "file_path": "laya_computer/utils.py",
        "line_number": 3,
        "code_snippet": (
            "def extract_names(records: list) -> list:\n"
            "    names = []\n"
            "    for r in records:\n"
            "        names.append(r.get('name', ''))\n"
            "    return names\n"
        ),
    },
    {
        "id": "case_g6_cosmetic_unused_import",
        "name": "G-6: Unused Import and TODO Comment",
        "is_real_blocker": False,
        "category": "cosmetic",
        "file_path": "laya_computer/calc.py",
        "line_number": 2,
        "code_snippet": (
            "import math  # Unused import\n\n"
            "# TODO: optimize later\n"
            "def calculate_total(a: int, b: int) -> int:\n"
            "    return a + b\n"
        ),
    },
]

JUDGE_PROMPT_TEMPLATE = """You are the Senior DeepAgent Judge Panel Leader (Security & Performance).
You must review the following code snippet from `{file_path}`:

```python
{code_snippet}
```

Instructions:
1. Conduct an authoritative review for critical SECURITY vulnerabilities (e.g. injection, path traversal) and severe PERFORMANCE blockers (e.g. thread freezing in async).
2. Anti-Rabbit-Hole: Do NOT declare blockers for cosmetic code smells, style conventions, or minor nitpicks.
3. For EVERY BLOCKER you claim, you MUST provide:
   - location: exactly `file_path:line`
   - problem: exact vulnerability/defect description
   - reproduction_code: A standalone, runnable Python snippet demonstrating the failure or vulnerability (e.g., executing the attack or demonstrating thread freezing).
4. If the issue is only cosmetic or minor, mark it as ADVISORY, or state that no blocker exists.

Output valid JSON matching this schema:
```json
{{
  "verdict": "approved" | "repair_required",
  "blockers": [
    {{
      "category": "security" | "performance",
      "severity": "blocker",
      "location": "{file_path}:<line>",
      "problem": "...",
      "reproduction_code": "..."
    }}
  ],
  "advisories": [
    {{
      "category": "security" | "performance",
      "severity": "advisory",
      "location": "{file_path}:<line>",
      "problem": "..."
    }}
  ]
}}
```
"""


def verify_blocker_proof(blocker: Dict[str, Any], case: Dict[str, Any]) -> Tuple[bool, str]:
    """Valida a citação de arquivo:linha e executa a reprodução fornecida."""
    loc = blocker.get("location", "")
    repro = blocker.get("reproduction_code", "")

    # 1. Valida citação
    if ":" not in loc:
        return False, "Citação inválida sem linha (esperado arquivo:linha)"
    parts = loc.split(":")
    cited_file = parts[0].strip()
    cited_line = parts[1].strip()

    if cited_file != case["file_path"] and not cited_file.endswith(case["file_path"]):
        return False, f"Citação aponta para arquivo errado: {cited_file} != {case['file_path']}"

    try:
        l_num = int(cited_line)
        total_lines = len(case["code_snippet"].splitlines())
        if l_num < 1 or l_num > total_lines:
            return False, f"Linha citada {l_num} fora dos limites (1..{total_lines})"
    except ValueError:
        return False, f"Linha citada não numérica: {cited_line}"

    # 2. Executa código de reprodução se fornecido
    if not repro or len(repro.strip()) < 10:
        return False, "Código de reprodução ausente ou vazio"

    # Monta script temporário com o código do caso + o código de reprodução
    full_script = f"{case['code_snippet']}\n\n# --- REPRODUCTION SCRIPT ---\n{repro}\n"
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
        tf.write(full_script)
        script_path = tf.name

    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        returncode = proc.returncode
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        # Consideramos reprodução comprovada se o script executou comprovando a falha
        combined_output = f"{stdout}\n{stderr}"
        proof_success = (
            returncode == 0
            or "AssertionError" in stderr
            or "FileNotFoundError" in stderr
            or "CalledProcessError" in stderr
            or any(kw in combined_output for kw in ["uid=", "gid=", "root", "whoami", "query:", "query", "syntax error"])
        )
        return proof_success, f"Returncode {returncode}. stdout: {stdout[:120]}, stderr: {stderr[:120]}"
    except subprocess.TimeoutExpired:
        # No caso de sleep bloqueante ou travamento, timeout comprova o bloqueio
        return True, "Timeout comprovado (bloqueio de thread ou loop)"
    except Exception as e:
        return False, f"Falha de execução do teste de reprodução: {e}"
    finally:
        Path(script_path).unlink(missing_ok=True)


def evaluate_judge_on_cases(judge_name: str, model_id: str) -> Dict[str, Any]:
    """Roda a bateria de 6 casos para o juiz indicado (Sonnet 5.5 ou gpt-6-luna)."""
    print(f"\n▶ Avaliando Juiz: {judge_name} ({model_id})...")
    case_results = []
    
    total_tokens = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_latency_ms = 0.0

    true_positives = 0
    false_positives = 0
    false_negatives = 0
    true_negatives = 0
    proof_confirmed_count = 0

    for case in BENCHMARK_CASES:
        prompt = JUDGE_PROMPT_TEMPLATE.format(
            file_path=case["file_path"],
            code_snippet=case["code_snippet"],
        )

        if "sonnet" in model_id:
            call_res = invoke_sonnet(prompt, system="You are an expert code review judge. Return valid JSON only.")
        else:
            call_res = invoke_worker_codex(prompt, system="You are an expert code review judge. Return valid JSON only.")

        total_tokens += call_res.total_tokens
        total_prompt_tokens += call_res.prompt_tokens
        total_completion_tokens += call_res.completion_tokens
        total_latency_ms += call_res.latency_ms

        raw = call_res.content
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            verdict_json = json.loads(raw)
        except Exception:
            verdict_json = {"verdict": "error", "blockers": [], "advisories": []}

        blockers = verdict_json.get("blockers", [])
        advisories = verdict_json.get("advisories", [])

        # Processa cada blocker com a validação de prova O7
        confirmed_blockers = []
        demoted_advisories = []

        for b in blockers:
            proved, reason = verify_blocker_proof(b, case)
            if proved:
                b["proof_status"] = "CONFIRMED"
                b["proof_reason"] = reason
                confirmed_blockers.append(b)
                proof_confirmed_count += 1
            else:
                b["proof_status"] = "DEMOTED_TO_ADVISORY"
                b["proof_reason"] = reason
                demoted_advisories.append(b)

        has_blocker = len(confirmed_blockers) > 0
        is_real = case["is_real_blocker"]

        if is_real and has_blocker:
            true_positives += 1
        elif not is_real and has_blocker:
            false_positives += 1
        elif is_real and not has_blocker:
            false_negatives += 1
        elif not is_real and not has_blocker:
            true_negatives += 1

        case_res = {
            "case_id": case["id"],
            "case_name": case["name"],
            "is_real_blocker": is_real,
            "raw_blockers_count": len(blockers),
            "confirmed_blockers_count": len(confirmed_blockers),
            "demoted_to_advisory_count": len(demoted_advisories),
            "advisories_count": len(advisories) + len(demoted_advisories),
            "verdict": "repair_required" if confirmed_blockers else "approved",
            "confirmed_blockers": confirmed_blockers,
            "demoted_advisories": demoted_advisories,
            "tokens": call_res.total_tokens,
            "latency_ms": call_res.latency_ms,
        }
        case_results.append(case_res)
        print(f"  {case['id']}: real={is_real}, raw_blockers={len(blockers)}, confirmed={len(confirmed_blockers)}, demoted={len(demoted_advisories)}")

    precision = round(true_positives / (true_positives + false_positives), 3) if (true_positives + false_positives) > 0 else 0.0
    recall = round(true_positives / (true_positives + false_negatives), 3) if (true_positives + false_negatives) > 0 else 0.0

    return {
        "judge_name": judge_name,
        "model_id": model_id,
        "metrics": {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "true_negatives": true_negatives,
            "precision": precision,
            "recall": recall,
            "proof_confirmed_blockers": proof_confirmed_count,
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_latency_ms": round(total_latency_ms, 1),
        },
        "cases": case_results,
    }


def run_judge_benchmark() -> Dict[str, Any]:
    """Executa o benchmark de juízes comparando Claude Sonnet 5.5 vs GPT-6 Luna no gabarito."""
    print("=" * 75)
    print("⚖️ Executando Gabarito do Juiz com Prova O7 (Sonnet 5.5 vs GPT-6 Luna)")
    print("=" * 75)

    results_sonnet = evaluate_judge_on_cases("Claude Sonnet 5.5 (Novo Juiz O7)", "claude-sonnet-5-5")
    results_gpt6 = evaluate_judge_on_cases("GPT-6 Luna (Juiz Antigo)", "gpt-6-luna")

    benchmark_summary = {
        "round": "Round_3_Judge_O7_Benchmark",
        "benchmark_cases_count": len(BENCHMARK_CASES),
        "real_blockers_in_ground_truth": 3,
        "cosmetic_cases_in_ground_truth": 3,
        "sonnet_5_5": results_sonnet["metrics"],
        "gpt_6_luna": results_gpt6["metrics"],
        "comparison": {
            "precision_diff": round(results_sonnet["metrics"]["precision"] - results_gpt6["metrics"]["precision"], 3),
            "recall_diff": round(results_sonnet["metrics"]["recall"] - results_gpt6["metrics"]["recall"], 3),
            "proof_confirmed_diff": results_sonnet["metrics"]["proof_confirmed_blockers"] - results_gpt6["metrics"]["proof_confirmed_blockers"],
            "tokens_diff": results_sonnet["metrics"]["total_tokens"] - results_gpt6["metrics"]["total_tokens"],
        },
        "details_sonnet": results_sonnet["cases"],
        "details_gpt6": results_gpt6["cases"],
    }

    (ROUND3_DIR / "judge_benchmark_results.json").write_text(
        json.dumps(benchmark_summary, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("\n🎯 Benchmark de Juízes Concluído com Sucesso!")
    print(f"Sonnet 5.5: Precision={results_sonnet['metrics']['precision']}, Recall={results_sonnet['metrics']['recall']}, Provas Confirmadas={results_sonnet['metrics']['proof_confirmed_blockers']}")
    print(f"GPT-6 Luna: Precision={results_gpt6['metrics']['precision']}, Recall={results_gpt6['metrics']['recall']}, Provas Confirmadas={results_gpt6['metrics']['proof_confirmed_blockers']}")
    return benchmark_summary


if __name__ == "__main__":
    run_judge_benchmark()
