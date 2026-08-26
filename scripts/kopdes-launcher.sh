#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${APP_ROOT}/.venv/bin/python"

cd "${APP_ROOT}"
exec "${VENV_PYTHON}" -m kopdes.main "$@"
