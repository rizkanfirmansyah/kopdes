#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICON_TARGET="${HOME}/.local/share/icons/hicolor/256x256/apps/kopdes.png"
LAUNCHER_TARGET="${HOME}/.local/bin/kopdes-launcher"

if [[ -e "${APP_ROOT}/.venv" && ! -w "${APP_ROOT}/.venv" ]]; then
  sudo rm -rf "${APP_ROOT}/.venv"
else
  rm -rf "${APP_ROOT}/.venv"
fi
rm -f "${HOME}/.local/share/applications/kopdes.desktop"
rm -f "${ICON_TARGET}"
rm -f "${LAUNCHER_TARGET}"

echo "[KOPDES] Removed local virtual environment, launcher, desktop entry, and app icon"
echo "[KOPDES] Database and key files under ~/.local/share/kopdes and ~/.config/kopdes were preserved"
