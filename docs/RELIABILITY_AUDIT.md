# KOPDES Deep Bug and Performance Audit

Date: 2026-08-28
Scope: desktop lifecycle, UI responsiveness, subprocess ownership, VPN/PPP/SSH managers, monitoring, persistence, logging, and security.

## Executive Result

The application was audited before the final reliability changes. The primary risks were not Qt rendering alone: long-lived Linux processes, timeout handling, stale runtime metadata, concurrent operations, and monitoring work were crossing lifecycle boundaries. The implementation now routes UI-facing work through a bounded worker pool, uses explicit persisted connection states, drains subprocess pipes, identifies owned processes, and performs bounded shutdown.

No live privileged VPN endpoint test was claimed. The local environment has OpenVPN 2 and NetworkManager tools, but does not have `openvpn3`; L2TP/PPTP plugin availability and real credentials were not exercised.

## Architecture Map

```text
main.py
  -> bootstrap.py (composition root, settings, database, dependency wiring)
  -> MainWindow / pages.py / widgets
  -> OperationController (keyed QThreadPool, max 4 workers)
  -> ControlCenterService (application use cases and runtime reconciliation)
  -> OpenVpnManager / PppManager / SshTunnelManager / RouteManager
  -> CommandRunner / psutil / filesystem / NetworkManager / Linux processes
  -> SQLite repositories and encrypted secret storage
```

UI widgets no longer construct arbitrary Linux commands. Service calls are submitted through `OperationController`; the system managers remain Linux-specific adapters. `MainWindow` owns timers and shutdown, while pages own presentation and signals.

Blocking or potentially slow operations found in the system layer include OpenVPN and PPP startup, SSH startup and listener probing, `nmcli`, `ip route`, `ip rule`, DNS resolution, ping/TCP/HTTP checks, `/proc` inspection, runtime log reads, and log export. These are now invoked from worker operations or bounded manager methods rather than the Qt event handler.

## Audit Method

- Inspected UI entry points, service orchestration, repositories, system managers, startup, shutdown, and all subprocess call sites.
- Searched for `shell=True`, `os.system`, `os.popen`, `subprocess.run`, `subprocess.call`, `pkill`, and `killall`.
- Reproduced the old command timeout behavior with a parent process that spawned a sleeping child. The parent returned on timeout while the child survived until process-group cleanup was added.
- Reproduced the import-order database failure by importing one repository and bootstrapping SQLite without the full application import graph.
- Reproduced the shared `tun0` telemetry ambiguity with two runtime sessions mapped to one interface.
- Ran unit, integration, regression, compile, Qt offscreen lifecycle, SQLite concurrency, and static safety checks.

## Findings and Fixes

### P1 - Subprocess timeout left descendants and could deadlock

BUG: Long-running commands could fill stdout or stderr pipe buffers. A timeout could return while a descendant still held the pipe or continued running.

ROOT CAUSE: Process output was not continuously drained and process ownership ended at the direct child instead of the command process group.

AFFECTED COMPONENT: `CommandRunner`; OpenVPN, PPP, route, diagnostics, and terminal operations.

FIX: `CommandRunner` now uses `selectors` to drain both pipes, caps each output tail at 256 KiB, starts commands in a new session, applies explicit timeouts, and sends TERM then KILL to the owned process group. Active processes are registered and can receive a shutdown signal.

WHY THIS FIX: It prevents pipe deadlock, bounds memory, and stops descendants without using global `killall` or `pkill`.

REGRESSION RISK: Some third-party commands may spawn processes outside their session or ignore signals; those cases still need protocol-specific live validation.

TEST PERFORMED: `tests/regression/test_command_runner.py` verifies output bounds, timeout cleanup, descendant cleanup after parent exit, redaction, and interruption of an active command.

### P1 - Runtime crash in automatic recovery

BUG: The monitoring path referenced an auto-retry limit that was not defined, causing a runtime exception when failed profiles became eligible for recovery.

ROOT CAUSE: Recovery policy was introduced without a class-level limit and without a smoke path exercising the timer-triggered branch.

AFFECTED COMPONENT: `ControlCenterService.recover_failed_connections` and dashboard auto-recovery.

FIX: Added `MAX_AUTO_RETRIES = 5`, exponential backoff capped at 32 seconds, retry eligibility checks, and failure persistence.

WHY THIS FIX: Failed connections cannot create an unbounded reconnect storm or crash the monitor.

REGRESSION RISK: A profile that needs more than five retries remains failed until an operator reconnects it or policy is changed.

TEST PERFORMED: Bounded recovery unit tests and offscreen Qt startup/shutdown smoke test.

### P1 - Shutdown did not have one owned-process boundary

BUG: Closing the application while a command or SSH tunnel was active could leave workers, pipes, or child network processes running.

ROOT CAUSE: Process handles were not centrally registered and shutdown was not ordered around timers, workers, managers, and UI destruction.

AFFECTED COMPONENT: `MainWindow`, `ControlCenterService`, `CommandRunner`, `SshTunnelManager`, OpenVPN managers.

FIX: Added per-manager process registries, durable PID metadata with process start time, owned process-group signaling, `request_stop_all`, manager shutdown methods, timer cancellation, pending-operation cancellation, and a bounded 15-second UI shutdown wait.

WHY THIS FIX: Only processes started or durably identified by KOPDES are targeted; unrelated user SSH/OpenVPN processes are not globally killed.

REGRESSION RISK: Root-owned processes still require PolicyKit or sudo authorization. If the authorization agent is unavailable, shutdown reports a bounded failure instead of waiting forever.

TEST PERFORMED: Active `CommandRunner` interruption test, manager lifecycle tests, and `ui-lifecycle-smoke` with `QT_QPA_PLATFORM=offscreen`.

### P1 - Privileged cleanup could be triggered by a monitoring timer

BUG: Reading stale classic OpenVPN metadata from a dashboard poll could invoke `pkexec` while trying to delete root-owned runtime files.

ROOT CAUSE: `list_sessions()` reused explicit disconnect cleanup, including privileged fallback, during passive monitoring.

AFFECTED COMPONENT: `ClassicOpenVpnManager.list_sessions` and dashboard refresh.

FIX: Polling uses non-privileged stale cleanup only. Explicit disconnect and shutdown retain privileged cleanup. Monitoring therefore cannot open an orphaned privilege prompt or wait for a privilege command on every refresh.

WHY THIS FIX: Observability must be read-only and bounded; privilege escalation belongs to an operator action or controlled shutdown.

REGRESSION RISK: Root-owned stale files may remain until an explicit cleanup path is authorized.

TEST PERFORMED: `test_classic_openvpn_polling_does_not_request_privileged_stale_cleanup`.

### P1 - UI event handlers could perform file or network work

BUG: Service calls and log export were reachable from UI signals, making it possible for slow system calls or file writes to stall Qt.

ROOT CAUSE: There was no single keyed asynchronous boundary between widgets and the application service.

AFFECTED COMPONENT: `MainWindow`, terminal, logs, profile actions, mapping actions, diagnostics, network refresh.

FIX: Added `OperationController` backed by a bounded `QThreadPool`, keyed duplicate rejection, cancellation, stale callback suppression, and worker-based log export. Dashboard, network, inspector, CRUD, diagnostics, connect, disconnect, reconnect, and SSH actions all use the controller.

WHY THIS FIX: The Qt event loop remains responsible for rendering and short UI interactions only.

REGRESSION RISK: A callback submitted during shutdown can be intentionally suppressed; UI state is recovered on the next refresh rather than updated after destruction.

TEST PERFORMED: Operation controller duplicate/cancellation tests and offscreen UI lifecycle smoke.

### P2 - Concurrent operations could create duplicate sessions

BUG: Rapid connect, disconnect, reconnect, or delete requests could overlap for one profile and create competing process/session state.

ROOT CAUSE: UI button state was not a sufficient concurrency guard and service methods lacked a per-profile synchronization boundary.

AFFECTED COMPONENT: `ControlCenterService` profile operations and `OperationController` action keys.

FIX: Added per-profile `RLock` guards, recent transition checks, active-state connect rejection, keyed UI operations, reconnect abort on failed disconnect, and latest-session identity checks during monitoring reconciliation.

WHY THIS FIX: The service remains safe even when called outside the current UI and handles reentrant reconnect logic without deadlocking.

REGRESSION RISK: A long system operation serializes actions for the same profile, which is intentional; different profiles remain independent.

TEST PERFORMED: Service state guard, reconnect failure, auto-retry limit, and operation-controller tests.

### P2 - Stale Active state and ambiguous interface telemetry

BUG: A persisted Active session could remain Active after its process or interface disappeared. Two profiles could also display identical RX/TX data when both were inferred from one `tun0`.

ROOT CAUSE: Status was inferred from persisted state or process existence without reconciling runtime identity and interface ownership.

AFFECTED COMPONENT: `SessionMonitor`, `ControlCenterService`, classic OpenVPN runtime metadata.

FIX: Runtime rows now reconcile pending sessions to Active only when a live interface is observed, convert timed-out/lost runtime sessions to Failed, record failure events, verify PID start time, and assign a tunnel interface to at most one session during a snapshot.

WHY THIS FIX: The dashboard reports observed health rather than trusting stale database state, and bandwidth is not duplicated across profiles.

REGRESSION RISK: If a backend cannot expose a unique interface, the row is marked degraded or does not claim telemetry instead of fabricating it.

TEST PERFORMED: Session promotion, reconnect-state, and shared-interface telemetry tests.

### P2 - PID reuse could target an unrelated process

BUG: A stale PID file could refer to a new process after the original VPN or SSH process exited.

ROOT CAUSE: PID number alone is not a process identity.

AFFECTED COMPONENT: Classic OpenVPN and SSH durable runtime metadata.

FIX: Metadata stores Linux `/proc` process start time and managers validate executable/command arguments, expected endpoint, and start time before status or termination. Legacy records without enough identity fail closed when permission probing is denied.

WHY THIS FIX: KOPDES refuses to kill a process it cannot positively associate with its own session.

REGRESSION RISK: Old runtime records may need explicit cleanup after upgrade; a process with inaccessible `/proc` data is reported unknown/stale rather than terminated.

TEST PERFORMED: Verified root-PID permission behavior and manager lifecycle tests.

### P2 - Log compaction could invalidate an active writer

BUG: Replacing an active log file with `os.replace` can leave OpenVPN or SSH appending to the old unlinked inode while readers use a new file.

ROOT CAUSE: File replacement is atomic for readers but not safe for an already-open append descriptor.

AFFECTED COMPONENT: OpenVPN and SSH runtime log maintenance.

FIX: Bounded log compaction now truncates and rewrites the existing inode in place, preserving the descriptor used by the managed process.

WHY THIS FIX: New log data remains visible through the same path while still bounding disk growth.

REGRESSION RISK: A concurrent writer can race with compaction and lose a small window of bytes; this is preferable to silently splitting the active log stream and remains bounded.

TEST PERFORMED: Inode-stability and active-writer log tests.

### P2 - OpenVPN3 deletion failures were hidden

BUG: If the OpenVPN3 backend refused profile deletion, the adapter could fall through and report a KOPDES-only deletion.

ROOT CAUSE: Backend failure was treated like backend unavailability.

AFFECTED COMPONENT: `OpenVpnManager.remove_profile`.

FIX: A real `remove_config` failure is returned to the UI. Fallback is allowed only when OpenVPN3 is unavailable and the profile is a legacy/classic record.

WHY THIS FIX: Operators receive truthful state and can correct the backend instead of believing the profile was deleted.

REGRESSION RISK: Profiles that exist only in OpenVPN3 remain visible after a failed deletion, which is correct and recoverable.

TEST PERFORMED: OpenVPN manager removal-failure regression test.

### P2 - SQLite initialization depended on import order

BUG: Calling database bootstrap after importing only one repository could raise `NoReferencedTableError` because foreign-key models were not registered in SQLAlchemy metadata.

ROOT CAUSE: `Base.metadata.create_all` was called without an explicit model import boundary.

AFFECTED COMPONENT: `bootstrap_database` and isolated repository consumers.

FIX: Database bootstrap imports every model module before creating tables. SQLite uses `check_same_thread=False`, WAL, busy timeout, pre-ping, and a ten-second connection timeout.

WHY THIS FIX: Startup and test behavior no longer depends on unrelated application import side effects, and concurrent writes have bounded lock waits.

REGRESSION RISK: `create_all` is not a schema migration system; production upgrades still need versioned migrations and backups.

TEST PERFORMED: Isolated event-log integration test and 16-worker SQLite stress test: 800 writes, 0 errors.

### P3 - Logs, terminal output, and telemetry history were unbounded

BUG: Long-running operation output and event history could grow memory or disk without a hard limit.

ROOT CAUSE: Live text widgets, event rows, and chart histories did not share bounded retention policies.

AFFECTED COMPONENT: event repository, rotating file logger, terminal, OpenVPN/SSH logs, session traffic history.

FIX: Event retention is capped at 10,000 rows, application logs rotate at 5 MiB with three backups, runtime reads cap at 2 MiB/2,000 lines, terminal document blocks are capped at 4,000, and traffic histories use bounded deques.

WHY THIS FIX: Resource usage remains predictable during long-running NOC operation.

REGRESSION RISK: Older evidence is intentionally unavailable in the live UI and must be exported or collected externally before retention expires.

TEST PERFORMED: Event retention, command output bound, runtime log, and chart model tests.

### P3 - Monitoring polling caused unnecessary system churn

BUG: Repeated interface, route, DNS, process, and system metric reads could be duplicated by independent UI refresh paths.

ROOT CAUSE: Collection and display were not separated and there were no keyed refresh operations or short caches.

AFFECTED COMPONENT: `MainWindow`, `InterfaceMonitor`, `RouteManager`, `SystemMetricsCollector`, `SessionMonitor`.

FIX: Dashboard, network, and inspector refreshes use distinct keyed operations and minimum intervals. Interface and route collectors cache short-lived snapshots; table models update rows incrementally; telemetry collection is separate from UI rendering.

WHY THIS FIX: CPU, subprocess, and database load stays proportional to the number of visible snapshots rather than accidental timer duplication.

REGRESSION RISK: A display can be up to one polling interval behind the kernel; an operator can manually refresh.

TEST PERFORMED: Full suite, offscreen lifecycle smoke, and static timer audit. No duplicate high-frequency timer was found.

## Subprocess and Security Review

- Source scan found no `shell=True`, `os.system`, `os.popen`, `subprocess.run`, `subprocess.call`, `pkill`, or `killall` in `src/kopdes`.
- Remaining `Popen` calls are centralized in `CommandRunner` and the SSH manager, use argv arrays, `close_fds`, `start_new_session`, bounded output handling, or file-backed logs.
- Command logs redact password, secret, VPN secret, and IPSec PSK values. OpenVPN auth files are mode 600 and removed during runtime cleanup.
- SQLite and profile storage contain encrypted secret fields. The secret key is mode 600 and startup fails closed if existing key permissions cannot be secured.
- SSH password forwarding uses `sshpass -d`, not a password argument. SSH host-key handling remains explicit through an application-owned known-hosts file.

## Remaining Risks

1. `PppManager` currently passes PPP and NetworkManager password values through command argv. `CommandRunner` redacts logs, but argv can still be visible to a privileged observer through `/proc`. The production fix should use NetworkManager D-Bus/keyfiles or a narrowly scoped privileged helper that receives secrets over a protected channel.
2. Generic `pppd call peer` lifecycle is peer-name based and does not yet have the same durable PID identity contract as classic OpenVPN and SSH. Live PPP failure and orphan testing is required before declaring that path production complete.
3. `openvpn3` is not installed in this environment, so official OpenVPN3 import/session-manage output and disconnect behavior were not live-tested. Adapter unit coverage exists, but command-output contract tests should be expanded with captured outputs from supported OpenVPN3 versions.
4. No live privileged VPN, PPP, L2TP, PPTP, or SSH endpoint was used. Network failure, authentication, route installation, and PolicyKit behavior therefore remain environment-dependent.
5. Coverage is `66%` after the current suite, below the requested 80% target. The largest gaps are system adapters and `ControlCenterService` branches.
6. SQLite still needs versioned migrations, backup/restore, and corruption recovery for production upgrades.
7. In-place log compaction is bounded best effort; a dedicated journald/file rotation strategy would reduce writer races.

## Verification Record

| Check | Result |
| --- | --- |
| Python compile | `python3 -m compileall -q src tests` passed |
| Full regression suite | `78 passed, 53 warnings` |
| Coverage | `66%` total, 6,218 statements |
| Isolated database regression | `1 passed` |
| SQLite stress | 16 workers, 800 events, `errors=0` |
| Qt lifecycle smoke | Startup, render, close, bounded shutdown passed |
| Static unsafe-command scan | No matches for global-kill or shell execution patterns |
| Shell syntax | `bash -n` passed for installer, uninstaller, launcher, and build scripts |
| Diff hygiene | `git diff --check` passed before report generation and is rerun after docs changes |

## Recommended Next Improvements

1. Raise coverage to at least 80% with deterministic fake-runner tests for PPP, L2TP/PPTP plugin failures, OpenVPN3 output variants, route failures, DNS failures, shutdown authorization failure, and UI stale callbacks.
2. Replace PPP/NM secret argv handling with a D-Bus or privileged-helper integration.
3. Add schema versioning and an atomic backup/restore migration command.
4. Add a live system-test profile that uses a disposable local OpenVPN/SSH fixture and verifies PID ownership, routes, interface state, failover, and clean machine shutdown.
5. Add structured metrics for operation latency, worker queue depth, subprocess count, memory usage, reconnect attempts, and cleanup failures.
6. Add protocol capability detection in the UI so unavailable L2TP/PPTP/OpenVPN3 backends show actionable install guidance before connect.
