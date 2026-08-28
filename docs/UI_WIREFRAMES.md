# KOPDES UI Wireframes

## Main window layout

### Header

- Application title
- Active environment badge
- Search bar
- Quick actions: import, add profile, connect, disconnect, diagnostics

### Status card row

- Total Connections
- Active Connections
- Failed Connections
- Bandwidth Usage
- System Load
- Memory Usage

### Main content split

Left pane:
- Connection table with filtering, tags, live state, latency, throughput, reconnect count, last error

Right pane:
- Selected profile detail tabs
- Overview
- Routing
- Health checks
- Logs
- Diagnostics

### Bottom workspace

- Embedded terminal panel
- Real-time activity log
- Notification strip

### Optional topology view

- Host node on the left
- Tunnel nodes in the center
- Remote endpoint nodes on the right
- Health color overlays per tunnel

## Visual direction

- Dark Linux-native operator dashboard
- Blue-green accent palette for healthy state
- Amber for degraded
- Red for failed
- Dense but readable tables
- Minimal ornamentation, high signal

## Implemented reference layout

The runtime shell follows the supplied reference/ prototypes while preserving the existing service layer:

- A persistent dark sidebar exposes Overview, Connections, SSH Tunnels, VPN Profiles, Network, Logs, Diagnostics, and Settings.
- The top bar contains the active page title, global search, Terminal dock toggle, and context-aware Add New action.
- Overview presents six compact metrics, recent activity, aggregate traffic chart, and network health.
- Connections uses a dense sortable table on the left and a Connection Inspector on the right. The inspector displays tunnel IP, gateway, DNS, RX/TX totals and rates, latency, packet loss, MTU, reconnect count, route table, interface data, logs, and upload/download fluctuation charts.
- SSH Tunnels presents explicit local-to-remote mapping paths, PID, uptime, status, and last error.
- Network exposes tun/tap/ppp interfaces, routes, policy rules, and DNS in tabs.
- Logs and Terminal remain available in a bottom QDockWidget, so operators can reclaim vertical space without losing the console.

The UI uses a bounded worker pool for all service and system operations. State is rendered as text plus color and transition actions are disabled per entity, not globally, so multiple independent sessions remain usable.
