#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "⚠️ Ambiente .venv não encontrado em $DIR. Criando com uv..."
    uv venv .venv
    uv pip install --python .venv/bin/python -e .
fi

echo "🚀 Iniciando Assistente de Voz Interativo do Graph Engineering Lab..."
exec .venv/bin/python run.py
