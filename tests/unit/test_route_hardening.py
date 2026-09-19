from __future__ import annotations

from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.route_manager import RouteManager



class RouteRunner:
    def __init__(self, outputs=None, return_code: int = 0, stderr: str = "") -> None:
        self.outputs = outputs or {}
        self.return_code = return_code
        self.stderr = stderr
        self.calls: list[list[str]] = []
        self.privileged_calls: list[list[str]] = []

    def run(self, command, timeout=30):
        self.calls.append(command)
        key = tuple(command[1:4])
        return CommandResult(
            command,
            self.return_code,
            self.outputs.get(key, self.outputs.get("default", "")),
            self.stderr,
        )

    def run_privileged(self, command, timeout=30, interactive=False):
        del timeout, interactive
        self.privileged_calls.append(command)
        return CommandResult(command, self.return_code, "", self.stderr)


def test_route_manager_parses_routes_rules_and_caches(monkeypatch) -> None:
    runner = RouteRunner(
        outputs={
            ("-j", "route", "show"): '[{"dst":"10.0.0.0/8","gateway":"10.0.0.1","dev":"tun0","table":100,"metric":20,"prefsrc":"10.0.0.2","protocol":"static","scope":"link"}]',
            ("-j", "rule", "show"): '[{"priority":100,"table":100,"from":"10.0.0.0/8","to":"0.0.0.0/0","action":"to-table"}]',
        }
    )
    monkeypatch.setattr("kopdes.infrastructure.system.route_manager.shutil.which", lambda _name: "/usr/sbin/ip")
    manager = RouteManager(runner)

    routes = manager.list_routes()
    cached_routes = manager.list_routes()
    rules = manager.list_rules()

    assert routes[0].table == "100"
    assert routes[0].source == "10.0.0.2"
    assert cached_routes == routes
    assert rules[0].priority == 100
    assert rules[0].table == "100"
    assert len(runner.calls) == 2


def test_route_manager_handles_command_and_json_failures(monkeypatch) -> None:
    runner = RouteRunner(return_code=1, stderr="ip failed")
    monkeypatch.setattr("kopdes.infrastructure.system.route_manager.shutil.which", lambda _name: "/usr/sbin/ip")
    manager = RouteManager(runner)
    assert manager.list_routes() == []
    assert manager.list_rules() == []

    runner.return_code = 0
    runner.outputs = {"default": "{bad"}
    manager._routes_cache = None
    manager._rules_cache = None
    assert manager.list_routes() == []
    assert manager.list_rules() == []


def test_route_manager_builds_mutating_commands_and_invalidates_cache(monkeypatch) -> None:
    runner = RouteRunner()
    manager = RouteManager(runner)

    added = manager.add_route("10.0.0.0/8", "10.0.0.1", "tun0", 10, "100")
    deleted = manager.delete_route("10.0.0.0/8", "100")
    changed = manager.change_metric("10.0.0.0/8", 50, device="tun0", table="100")

    assert added.success and deleted.success and changed.success
    assert runner.privileged_calls == [
        ["ip", "route", "add", "10.0.0.0/8", "via", "10.0.0.1", "dev", "tun0", "metric", "10", "table", "100"],
        ["ip", "route", "del", "10.0.0.0/8", "table", "100"],
        ["ip", "route", "replace", "10.0.0.0/8", "dev", "tun0", "metric", "50", "table", "100"],
    ]


def test_route_manager_rejects_invalid_input_and_reports_mutation_failure() -> None:
    runner = RouteRunner(return_code=2, stderr="permission denied")
    manager = RouteManager(runner)

    assert not manager.add_route("bad route").success
    assert not manager.add_route("10.0.0.0/8", metric=0).success
    assert not manager.add_route("10.0.0.0/8", gateway="bad gateway").success
    assert not manager.delete_route("10.0.0.0/8", table="").success
    assert not manager.change_metric("10.0.0.0/8", "bad").success
    failed = manager.add_route("10.0.0.0/8")

    assert failed.success is False
    assert failed.message == "Failed to add route."
    assert failed.details == "permission denied"


def test_route_manager_returns_empty_when_ip_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.route_manager.shutil.which", lambda _name: None)
    manager = RouteManager(RouteRunner())
    assert manager.list_routes() == []
    assert manager.list_rules() == []
