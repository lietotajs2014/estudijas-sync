#!/bin/bash
# macOS / Linux: dubultklikšķis (macOS) vai ./start.command
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "Python nav atrasts: https://www.python.org/downloads/"; read -r; exit 1; fi
if [ ! -f "$HOME/.estudijas_sync/.deps_ok" ]; then
  echo "Pirmā palaišana: instalē bibliotēkas…"
  "$PY" -m pip install -q -r requirements.txt && "$PY" -m playwright install chromium || { read -r; exit 1; }
  mkdir -p "$HOME/.estudijas_sync" && touch "$HOME/.estudijas_sync/.deps_ok"
fi
"$PY" run.py web
