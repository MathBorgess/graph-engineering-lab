#!/usr/bin/env python3
"""Ponto de entrada direto para o Assistente de Voz Interativo (S2S)."""

import sys
from pathlib import Path

# Adicionar pasta raiz ao path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from voice_lab.agents.runner import run_interactive_s2s

if __name__ == "__main__":
    run_interactive_s2s()
