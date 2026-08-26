# KOPDES Review And Redesign

## Review findings

1. The main window is still a static dashboard shell with one table and a placeholder topology tab, so the center-right workspace does not expose a real connection inspector or operator workflow.
2. The network engine only prepares command plans and never executes, monitors, reconnects, or reconciles live sessions.
3. The import parser does not implement OpenVPN3 import or persistent system integration; it only extracts a few fields from files.
4. The connection model and table do not represent runtime VPN state such as tunnel IP, gateway, interface, RX/TX, latency, packet loss, or reconnect count.
5. Routing, DNS, and interface monitoring are absent from both the backend and UI.
6. PPP, PPPoE, PPTP, L2TP, and L2TP/IPSec management are not exposed through real forms or backend adapters.
7. The storage layer encrypts credentials, but there is no system secret backend abstraction or runtime privilege strategy around high-impact operations.

## New UI architecture

- Top area: status cards for total, active, failed, bandwidth, load, memory.
- Center-left: searchable connection list with action toolbar.
- Center-right: connection inspector using `QStackedWidget` and a route/interface/DNS/log workspace.
- Bottom: `QDockWidget` with logs and terminal.
- Layout primitives: `QSplitter`, `QTableView`, `QDockWidget`, `QStackedWidget`.

## Database schema

Existing schema remains valid for the current codebase with these practical conventions:

- `connection_profiles.config_payload` stores protocol-specific attributes such as `interface_name`, `peer_name`, `ipsec_psk`, and imported OpenVPN3 config references.
- `connection_sessions` stores the latest lifecycle outcome and reconnect history.
- `event_logs` stores operational actions and errors.

Recommended next migration:

- add explicit columns for `profile_source`, `system_profile_ref`, `last_interface_name`, and `secret_backend`.

## Backend architecture

- `ControlCenterService`: orchestration boundary for UI actions and runtime aggregation.
- `OpenVpn3Manager`: wrappers for import, list, connect, disconnect, delete, and session parsing.
- `PppManager`: wrappers for PPP, PPPoE, PPTP, L2TP, and L2TP/IPSec using `nmcli` and `pppd`.
- `RouteManager`: `ip route` and `ip rule` listing and mutation.
- `InterfaceMonitor`: `tun`, `tap`, and `ppp` interface metrics.
- `DnsMonitor`: resolver inspection.
- `SessionMonitor`: runtime composition for tables and inspector views.

## OpenVPN manager module

- wraps `openvpn3 config-import`
- wraps `openvpn3 configs-list`
- wraps `openvpn3 session-start`
- wraps `openvpn3 sessions-list`
- wraps `openvpn3 session-manage`
- uses `config-remove` for delete

## PPP manager module

- manual profile creation and editing via GUI
- PPP via `pppd call`
- PPPoE via `nmcli connection add type pppoe`
- PPTP and L2TP via `nmcli connection add type vpn`
- disconnect and delete wrappers

## Route manager module

- list routes via `ip -j route show table all`
- list rules via `ip -j rule show`
- add route
- delete route
- change route metric

## Interface monitor module

- filters `tun*`, `tap*`, `ppp*`
- displays total RX/TX, current throughput, errors, MTU, and IP

## Session monitor module

- merges stored profiles with OpenVPN3 sessions, active PPP connections, interface counters, routes, and DNS
- computes inspector data for the selected connection

## Security architecture

- encrypted SQLite remains the current credential backend
- application-level secret manager preserves ciphertext at rest
- next hardening step: pluggable Linux Secret Service backend and privilege mediation for route and VPN operations

## Test plan

- unit tests for parsers, managers, and control-plane service
- integration tests for repositories and encrypted storage
- e2e smoke for Qt bootstrap and main layout
- future contract tests for OpenVPN3 and nmcli CLI adapters with fixture outputs

## Deployment plan

- desktop-first deployment on Ubuntu 22.04, Ubuntu 24.04, Debian 12
- `.venv` install path with `install.sh`
- optional Docker/Compose for CI and backend validation
- future `.deb` packaging with dependency detection for OpenVPN3 and NetworkManager plugins

## Step-by-step implementation roadmap

1. Stabilize control-plane service and runtime monitors.
2. Complete responsive operator layout and inspector interactions.
3. Harden OpenVPN3 import and session parsing against real CLI outputs.
4. Add richer PPP/L2TP validation and plugin detection.
5. Introduce background workers for polling and long-running commands.
6. Add privileged operation strategy.
7. Introduce migrations and explicit protocol metadata columns.
8. Expand integration and regression coverage around live adapters.
