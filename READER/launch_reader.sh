#!/usr/bin/env bash
# Launcher script for BalloonsTranslator Manga Reader (Linux/macOS)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
WORKSPACE_DIR="$( cd "$SCRIPT_DIR/.." &> /dev/null && pwd )"

if [ -z "$PYTHON" ]; then
    if [ -x "$WORKSPACE_DIR/.venv/bin/python" ]; then
        PYTHON="$WORKSPACE_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="python3"
    else
        PYTHON="python"
    fi
fi

exec "$PYTHON" "$SCRIPT_DIR/launch_reader.py" "$@"

