# KOPDES

KOPDES (Konfigurator OVPN & PPP Dashboard Endpoint System) is a Linux desktop application for centralized VPN and PPP endpoint management, monitoring, diagnostics, and automation.

## Current scope

This repository contains the production-grade foundation for:

- Clean Architecture project layout
- SQLite persistence with SQLAlchemy
- Encrypted credential storage
- PySide6 dashboard shell
- System command abstraction and diagnostics hooks
- Initial VPN engine abstractions
- Installer, container, and test scaffolding

Protocol-specific production integrations are staged so OpenVPN and PPP family support can be expanded safely in later phases.

## SSH local port mapping

KOPDES can manage multiple SSH local forwards, for example:

```text
127.0.0.1:5433 -> localhost:5432 via boss@192.168.0.10:22
```

Mappings are persisted in SQLite with encrypted passwords. Runtime metadata contains only the managed PID and endpoint details; password authentication uses `sshpass -d` so the password is not placed in the process argument list. SSH identity files or an SSH agent are preferred. Install `openssh-client` and `sshpass` with `install.sh`, then open the `SSH Port Mapping` tab in the bottom dock to add, edit, connect, disconnect, or delete mappings.

## PPP and L2TP runtime dependencies

PPP-family profiles are activated through NetworkManager. L2TP and L2TP/IPSec require the NetworkManager plugin in addition to the base `network-manager` package:

```bash
sudo apt-get install network-manager-l2tp network-manager-l2tp-gnome xl2tpd strongswan
sudo systemctl restart NetworkManager
```

PPTP requires `network-manager-pptp`; OpenVPN profiles using the NetworkManager backend require `network-manager-openvpn`. `install.sh` checks and attempts to install these packages. If APT is blocked by an unrelated third-party repository, fix that repository first and rerun the installer, or install the packages manually.

## Stack

- Python 3.12+
- PySide6
- SQLAlchemy
- SQLite
- Bash
- YAML
- psutil
- cryptography

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m kopdes.main
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Database Schema](docs/DATABASE_SCHEMA.md)
- [UI Wireframes](docs/UI_WIREFRAMES.md)
- [Deployment Plan](docs/DEPLOYMENT_PLAN.md)

## Testing

```bash
pytest
```

## Installation

```bash
bash install.sh
```
