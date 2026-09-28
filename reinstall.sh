#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[KOPDES] Reinstalling: uninstall then install"
"${APP_ROOT}/uninstall.sh"
"${APP_ROOT}/install.sh"
echo "[KOPDES] Reinstall complete"
