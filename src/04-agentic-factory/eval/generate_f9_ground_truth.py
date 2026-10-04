"""Gera o gabarito formal de conceitos para o Experimento F9 usando Claude Sonnet 5.5."""

import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from agents.llm_client import invoke_sonnet

prompt = """You are the Lead Evaluator for agent memory systems.
Formulate a formal Ground Truth (gabarito) of concepts discoverable across 3 sequential tasks in laya-computer:
1. Task 1: Preflight reachability traversal (discovering linear chain via next_step, ignoring on_failure).
2. Task 2: Destructive key risk detection (discovering lexical matching of shortcuts without OS execution).
3. Task 3: Start_step configurability and superseding the previous assumption about always starting at steps[0].

Output ONLY a JSON block:
```json
{
  "concepts": [
    {
      "concept_id": "preflight-reachability-linear",
      "claim": "Alcançabilidade linear em preflight segue estritamente next_step a partir de first_step_id; referências em on_failure não devem ser seguidas durante análise normal de pré-voo.",
      "expected_evidence": "laya_computer/preflight.py:37",
      "supersedes": null
    },
    {
      "concept_id": "destructive-keys-lexical",
      "claim": "Atalhos perigosos de teclado e comandos com 'command' ou 'terminal' são identificados estaticamente via casing normalizado sem efeitos colaterais no SO.",
      "expected_evidence": "laya_computer/preflight.py:53",
      "supersedes": null
    },
    {
      "concept_id": "preflight-reachability-v2",
      "claim": "O ponto de partida de alcançabilidade deve respeitar plan.start_step quando fornecido explicitamente, invalidando a premissa de que o primeiro passo é sempre steps[0].id.",
      "expected_evidence": "laya_computer/plan.py:126",
      "supersedes": "preflight-reachability-linear"
    }
  ]
}
```
"""

def generate():
    res = invoke_sonnet(prompt, system="Output only valid JSON.")
    raw = res.content
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    data = json.loads(raw)
    out_file = FACTORY_DIR / "eval" / "round3" / "f9_ground_truth.json"
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Gabarito F9 gerado com sucesso pelo Claude Sonnet 5.5!")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return data

if __name__ == "__main__":
    generate()
