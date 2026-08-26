#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${APP_ROOT}/.venv"
DESKTOP_FILE="${HOME}/.local/share/applications/kopdes.desktop"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
ICON_TARGET="${ICON_DIR}/kopdes.png"
LOGO_SOURCE="${APP_ROOT}/logo.png"
LAUNCHER_SOURCE="${APP_ROOT}/scripts/kopdes-launcher.sh"
LAUNCHER_TARGET="${HOME}/.local/bin/kopdes-launcher"

warn() {
  echo "[KOPDES] Warning: $*" >&2
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

apt_package_installed() {
  if ! have_cmd dpkg-query; then
    return 1
  fi
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

ensure_not_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    echo "[KOPDES] Error: do not run install.sh with sudo or as root." >&2
    echo "[KOPDES] Run it as your normal desktop user so the app launcher and venv are owned correctly." >&2
    exit 1
  fi
}

reset_unwritable_venv() {
  if [[ ! -e "${VENV_DIR}" ]]; then
    return 0
  fi
  if [[ -w "${VENV_DIR}" ]] && [[ ! -d "${VENV_DIR}/bin" || -w "${VENV_DIR}/bin" ]]; then
    return 0
  fi

  warn "Existing virtual environment is not writable by ${USER}. Recreating it."
  if have_cmd sudo; then
    sudo rm -rf "${VENV_DIR}"
  else
    echo "[KOPDES] Error: existing ${VENV_DIR} is not writable and sudo is unavailable." >&2
    exit 1
  fi
}

apt_install_if_possible() {
  if ! have_cmd apt-get; then
    return 0
  fi

  local need_apt=0
  if ! have_cmd python3; then
    need_apt=1
  fi
  if ! python3 -m venv --help >/dev/null 2>&1; then
    need_apt=1
  fi
  if ! have_cmd pip3; then
    need_apt=1
  fi
  if ! have_cmd openvpn; then
    need_apt=1
  fi
  if ! have_cmd sshpass; then
    need_apt=1
  fi
  if ! have_cmd nmcli; then
    need_apt=1
  fi
  if have_cmd dpkg-query && ! apt_package_installed network-manager-l2tp; then
    need_apt=1
  fi
  if have_cmd dpkg-query && ! apt_package_installed network-manager-pptp; then
    need_apt=1
  fi

  if [[ "${need_apt}" -eq 0 ]]; then
    echo "[KOPDES] Core system dependencies already available, skipping apt install"
    return 0
  fi

  echo "[KOPDES] Attempting to install missing runtime dependencies via apt"
  if ! sudo apt-get update; then
    warn "apt-get update failed because of a host repository issue."
    warn "KOPDES install will continue with existing dependencies. Fix the broken APT repository separately if packages are still missing."
    return 0
  fi

  if ! sudo apt-get install -y python3 python3-venv python3-pip openvpn ppp iproute2 network-manager openssh-client sshpass network-manager-l2tp network-manager-pptp network-manager-openvpn xl2tpd strongswan; then
    warn "apt-get install failed. Continuing with whatever dependencies are already installed."
  fi
}

ensure_python() {
  if ! have_cmd python3; then
    echo "[KOPDES] Error: python3 is required but not installed." >&2
    exit 1
  fi
}

ensure_venv_module() {
  if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "[KOPDES] Error: python3-venv is required but unavailable." >&2
    echo "[KOPDES] Fix your APT repositories, then install python3-venv manually." >&2
    exit 1
  fi
}

echo "[KOPDES] Preparing installation"
ensure_not_root
apt_install_if_possible
ensure_python
ensure_venv_module
reset_unwritable_venv

echo "[KOPDES] Creating virtual environment"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

echo "[KOPDES] Installing Python package"
pip install --upgrade pip
pip install --force-reinstall -e "${APP_ROOT}[dev]"

mkdir -p "${HOME}/.local/share/applications"
mkdir -p "${ICON_DIR}"
mkdir -p "${HOME}/.local/bin"

ICON_VALUE="utilities-terminal"
if [[ -f "${LOGO_SOURCE}" ]]; then
  cp "${LOGO_SOURCE}" "${ICON_TARGET}"
  ICON_VALUE="${ICON_TARGET}"
  echo "[KOPDES] Installed application icon from ${LOGO_SOURCE}"
else
  rm -f "${ICON_TARGET}"
  echo "[KOPDES] logo.png not found in project root, using fallback icon"
fi

cat > "${LAUNCHER_TARGET}" <<EOF_LAUNCHER
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT}"
VENV_PYTHON="${VENV_DIR}/bin/python"
LOG_DIR="${HOME}/.cache/kopdes"
LOG_FILE="\${LOG_DIR}/desktop-launch.log"

mkdir -p "\${LOG_DIR}"
{
  echo "===== \$(date '+%Y-%m-%d %H:%M:%S %z') ====="
  echo "PWD(before)=\$(pwd)"
  echo "APP_ROOT=${APP_ROOT}"
  echo "DISPLAY=\${DISPLAY:-}"
  echo "WAYLAND_DISPLAY=\${WAYLAND_DISPLAY:-}"
  echo "XDG_CURRENT_DESKTOP=\${XDG_CURRENT_DESKTOP:-}"
  echo "XDG_SESSION_TYPE=\${XDG_SESSION_TYPE:-}"
  echo "USER=\$(id -un)"
  echo "VENV_PYTHON=${VENV_DIR}/bin/python"
} >> "\${LOG_FILE}" 2>&1

cd "${APP_ROOT}"
echo "PWD(after)=\$(pwd)" >> "\${LOG_FILE}" 2>&1
echo "Launching KOPDES via setsid" >> "\${LOG_FILE}" 2>&1
exec setsid "${VENV_DIR}/bin/python" -u -m kopdes.main "\$@" >> "\${LOG_FILE}" 2>&1
EOF_LAUNCHER
chmod +x "${LAUNCHER_TARGET}"

cat > "${DESKTOP_FILE}" <<EOF_DESKTOP
[Desktop Entry]
Type=Application
Name=KOPDES
Comment=Konfigurator OVPN & PPP Dashboard Endpoint System
Exec=${LAUNCHER_TARGET}
TryExec=${LAUNCHER_TARGET}
Path=${APP_ROOT}
Icon=${ICON_VALUE}
Terminal=false
Categories=Network;System;
Keywords=vpn;openvpn;ppp;l2tp;network;
StartupNotify=false
StartupWMClass=KOPDES
EOF_DESKTOP

chmod +x "${DESKTOP_FILE}"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "[KOPDES] Installation complete"
