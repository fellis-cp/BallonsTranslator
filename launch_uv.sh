#!/usr/bin/env sh

set -eu

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

command -v uv >/dev/null 2>&1 || fail "uv is not installed. Install it from https://docs.astral.sh/uv/"

resolve_script_dir() {
    script=$0

    case "$script" in
        */*) ;;
        *)
            found=$(command -v "$script" 2>/dev/null || true)
            [ -n "$found" ] && script=$found
            ;;
    esac

    script_dir=$(CDPATH= cd "$(dirname "$script")" && pwd -P)
    printf '%s\n' "$script_dir"
}

APP_DIR=$(resolve_script_dir)

cd "$APP_DIR"

exec uv run --with-requirements requirements.txt --python 3.12 python -m ballontranslator "$@"
