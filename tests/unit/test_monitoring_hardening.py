from __future__ import annotations

from pathlib import Path

from kopdes.infrastructure.system.dns_monitor import DnsMonitor
from kopdes.infrastructure.system.interface_monitor import InterfaceMonitor
from kopdes.infrastructure.system.command_runner import CommandResult




def test_dns_monitor_parses_servers_and_search_domains(tmp_path: Path) -> None:
    path = tmp_path / "resolv.conf"
    path.write_text(
        "nameserver 1.1.1.1\nsearch corp.example lab.example\nnameserver 9.9.9.9\n",
        encoding="utf-8",
    )

    status = DnsMonitor(path).collect()

    assert status.servers == ["1.1.1.1", "9.9.9.9"]
    assert status.search_domains == ["corp.example", "lab.example"]
    assert status.resolver_source == str(path)


def test_dns_monitor_handles_missing_and_unreadable_files(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "missing"
    assert DnsMonitor(missing).collect().servers == []

    path = tmp_path / "unreadable"
    path.write_text("nameserver 8.8.8.8\n", encoding="utf-8")
    monkeypatch.setattr("kopdes.infrastructure.system.dns_monitor.Path.read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied")))

    status = DnsMonitor(path).collect()

    assert status.servers == []
    assert status.resolver_source == str(path)


class DiagnosticRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.commands: list[list[str]] = []

    def run(self, command, timeout=30):
        self.commands.append(command)
        return CommandResult(command, self.result.return_code, self.result.stdout, self.result.stderr)


def test_health_monitor_validates_targets_and_reports_ping(monkeypatch) -> None:
    from kopdes.infrastructure.system.health_monitor import HealthMonitor
    from kopdes.shared.enums import HealthCheckType

    runner = DiagnosticRunner(CommandResult([], 0, "time=12.4 ms", ""))
    monitor = HealthMonitor(runner)

    empty = monitor.run(HealthCheckType.PING, "")
    success = monitor.run(HealthCheckType.PING, "example.net", timeout=2)

    assert empty.ok is False
    assert success.ok is True
    assert success.latency_ms is not None
    assert runner.commands[-1] == ["ping", "-c", "1", "-W", "2", "example.net"]

    runner.result = CommandResult([], 1, "", "network unreachable")
    failed = monitor.run(HealthCheckType.PING, "example.net")
    assert failed.ok is False
    assert failed.latency_ms is None
    assert failed.detail == "network unreachable"


def test_health_monitor_tcp_success_and_failures(monkeypatch) -> None:
    from kopdes.infrastructure.system.health_monitor import HealthMonitor
    from kopdes.shared.enums import HealthCheckType

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    runner = DiagnosticRunner(CommandResult([], 0, "", ""))
    monitor = HealthMonitor(runner)
    monkeypatch.setattr(
        "kopdes.infrastructure.system.health_monitor.socket.create_connection",
        lambda _address, timeout: Socket(),
    )

    success = monitor.run(HealthCheckType.TCP, "127.0.0.1:5432")
    invalid_format = monitor.run(HealthCheckType.TCP, "127.0.0.1")
    invalid_port = monitor.run(HealthCheckType.TCP, "127.0.0.1:99999")

    assert success.ok is True
    assert invalid_format.ok is False
    assert invalid_port.ok is False

    def fail(_address, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(
        "kopdes.infrastructure.system.health_monitor.socket.create_connection",
        fail,
    )
    failed = monitor.run(HealthCheckType.TCP, "127.0.0.1:5432")
    unsupported = monitor.run(HealthCheckType.HTTP, "example.net")
    assert failed.ok is False
    assert "refused" in failed.detail
    assert unsupported.ok is False


def test_interface_monitor_collects_rates_and_uses_bounded_cache(monkeypatch) -> None:
    from types import SimpleNamespace

    import psutil

    monitor = InterfaceMonitor()
    monitor._last_counters = {
        "tun0": SimpleNamespace(bytes_recv=100, bytes_sent=200, errin=1, errout=2),
    }
    monitor._last_ts = 1.0
    monkeypatch.setattr("kopdes.infrastructure.system.interface_monitor.monotonic", lambda: 2.0)
    monkeypatch.setattr(
        psutil,
        "net_if_stats",
        lambda: {"tun0": SimpleNamespace(isup=True, mtu=1400), "eth0": SimpleNamespace(isup=True, mtu=1500)},
    )
    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        lambda: {"tun0": [SimpleNamespace(family=2, address="10.0.0.2")]},
    )
    monkeypatch.setattr(
        psutil,
        "net_io_counters",
        lambda pernic=False: (
            {
                "tun0": SimpleNamespace(bytes_recv=300, bytes_sent=500, errin=3, errout=4),
            }
            if pernic
            else SimpleNamespace(bytes_recv=0, bytes_sent=0)
        ),
    )

    snapshots = monitor.collect()
    cached = monitor.collect()

    assert snapshots[0].name == "tun0"
    assert snapshots[0].rx_bytes == 300
    assert snapshots[0].tx_bytes == 500
    assert snapshots[0].ipv4 == "10.0.0.2"
    assert snapshots[0].rx_rate_bps == 200.0
    assert cached == snapshots


def test_system_metrics_collects_and_handles_psutil_failure(monkeypatch) -> None:
    from kopdes.infrastructure.system.system_metrics import SystemMetricsCollector

    collector = SystemMetricsCollector()
    from types import SimpleNamespace
    collector._last_io = SimpleNamespace(bytes_recv=1000, bytes_sent=1000)
    collector._last_sample_at = 1.0
    monkeypatch.setattr("kopdes.infrastructure.system.system_metrics.psutil.getloadavg", lambda: (0.75, 0.0, 0.0))
    monkeypatch.setattr(
        "kopdes.infrastructure.system.system_metrics.psutil.virtual_memory",
        lambda: type("Memory", (), {"percent": 42.5})(),
    )
    monkeypatch.setattr(
        "kopdes.infrastructure.system.system_metrics.psutil.net_io_counters",
        lambda: type("IO", (), {"bytes_recv": 2000, "bytes_sent": 4000})(),
    )
    monkeypatch.setattr("kopdes.infrastructure.system.system_metrics.monotonic", lambda: 2.0)

    metrics = collector.collect()
    assert metrics.system_load == 0.75
    assert metrics.memory_usage_percent == 42.5
    assert metrics.bandwidth_usage_mbps > 0

    monkeypatch.setattr(
        "kopdes.infrastructure.system.system_metrics.psutil.virtual_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
    )
    failed = collector.collect()
    assert failed.bandwidth_usage_mbps == 0.0
