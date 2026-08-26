# KOPDES Architecture

## 1. System intent

KOPDES is a Linux desktop control plane for VPN and PPP endpoints. It centralizes configuration, runtime state, diagnostics, logging, failover policy, and operator actions while delegating low-level tunnel operations to Linux-native tools such as `nmcli`, `openvpn`, `pppd`, `ip`, `journalctl`, and `systemd`.

## 2. Architecture style

The project uses Clean Architecture with explicit boundaries:

- UI Layer: PySide6 widgets, table models, dialogs, notifications.
- Application Layer: use cases, DTOs, orchestration, policy coordination.
- Domain Layer: entities, value objects, protocol and lifecycle rules.
- Infrastructure Layer: database, encryption, logging, filesystem, YAML, command execution.
- Repository Layer: repository interfaces and SQLAlchemy implementations.
- Service Layer: monitoring, diagnostics, import parsing, routing, failover, reconnection policy.
- System Layer: Linux integration adapters for networking and service control.

## 3. Runtime components

### Desktop shell

- Starts the Qt application
- Loads configuration
- Initializes logging and database
- Wires repositories and services
- Launches the dashboard

### Network engine

- Manages protocol handlers
- Starts and stops sessions
- Tracks runtime state
- Emits health and lifecycle events

### Monitoring engine

- Polls system metrics
- Runs latency and health checks
- Collects bandwidth counters
- Pushes updates to the UI

### Storage engine

- Stores profiles, policies, tags, sessions, logs, and encrypted secrets
- Preserves auditability and reconnect history

## 4. Protocol strategy

Protocol support is layered to avoid coupling UI logic to system commands.

- Priority 1 handlers: `openvpn`, `ppp`, `pptp`, `l2tp`, `l2tp-ipsec`, `pppoe`
- Priority 2 handlers: `wireguard`, `sstp`, `ipip`, `gre`
- Priority 3 handlers: `openconnect`, `softether`

Each handler implements a shared engine contract:

- validate configuration
- render runtime command plan
- start session
- stop session
- collect status
- collect logs
- support health checks

## 5. Routing model

Routing is expressed through policy objects:

- default route override
- split tunnel
- route metrics
- custom route table
- source-based policy
- host or subnet pinning
- failover chain

Linux integration uses `ip route`, `ip rule`, and NetworkManager or protocol-specific tools where appropriate.

## 6. Security model

- Secrets are encrypted at rest using a locally managed symmetric key with strict file permissions.
- The database stores ciphertext only, never plaintext passwords.
- UI masks secrets by default.
- Command execution is centralized and validated.
- Role separation is prepared through an authorization service boundary.
- Session timeout and unlock flows are represented in application services.

## 7. Observability

- Structured application logs
- Persistent event log table
- UI-visible operator log stream
- Metrics snapshots for dashboard cards
- Error categorization for user-friendly messages

## 8. Phase plan

### Phase 1: Architecture

- Project structure
- Dependency graph
- Application bootstrap
- Documentation set

Code review:
- Confirm imports respect layer boundaries
- Confirm system integration remains adapter-based

Security review:
- Confirm secrets are never modeled as plaintext persistence fields

Optimization review:
- Keep UI polling and DB writes bounded

Breaking change check:
- Safe, no protocol runtime exposed yet

### Phase 2: Database

- SQLite schema
- SQLAlchemy models
- repositories
- migrations strategy placeholder

Code review:
- Validate indexes and cascade behavior

Security review:
- Ensure encrypted secret blobs are isolated

Optimization review:
- Add indexes on status, tags, and timestamps

Breaking change check:
- Schema versioning required before production upgrade

### Phase 3: Backend Core

- Use cases
- import parsers
- diagnostics and command runner abstractions

Code review:
- Confirm command construction is deterministic

Security review:
- Validate input sanitization and allowlist behavior

Optimization review:
- Reuse database sessions carefully

Breaking change check:
- Preserve repository interfaces

### Phase 4: VPN Engine

- protocol handlers
- runtime registry
- reconnect and failover orchestration

Code review:
- Confirm handler-specific command generation

Security review:
- Prevent shell injection and privilege escalation

Optimization review:
- Avoid high-frequency subprocess churn

Breaking change check:
- Contract tests per protocol handler

### Phase 5: Dashboard

- status cards
- connection table
- logs
- embedded terminal
- topology placeholder

Code review:
- Check model-view separation

Security review:
- Ensure secret masking in forms and logs

Optimization review:
- Incremental refresh instead of full-table rebuild

Breaking change check:
- UI must tolerate missing metrics

### Phase 6: Monitoring

- latency, traffic, packet loss, health checks
- desktop notifications

Code review:
- Verify event deduplication and threshold logic

Security review:
- Limit diagnostic command surface

Optimization review:
- Backoff and jitter in recurring checks

Breaking change check:
- Monitoring failures must not kill active tunnels

### Phase 7: Testing

- unit, integration, smoke, e2e, regression

Code review:
- Check assertions for domain invariants

Security review:
- Add tests for secret handling and command validation

Optimization review:
- Separate slow and fast suites

Breaking change check:
- Baseline workflows become regression fixtures

### Phase 8: Packaging

- install and uninstall scripts
- Docker and Compose
- release build scripts

Code review:
- Confirm distro-specific package handling

Security review:
- Restrict file permissions and service execution

Optimization review:
- Minimize runtime dependencies

Breaking change check:
- Preserve config and database backups during upgrade

## 9. Future roadmap

- Full protocol handlers for all listed transports
- Interactive topology graph
- RBAC and multi-user mode
- Plugin system for custom diagnostics
- Remote agent architecture for centralized fleet control
- Exportable audit reports
- Policy simulation and dry-run routing preview
