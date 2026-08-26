from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.route_manager import RouteManager


class FakeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout

    def run(self, command, timeout=30):
        return CommandResult(command=command, return_code=0, stdout=self.stdout, stderr="")


def test_route_manager_parses_ip_json(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ip")
    manager = RouteManager(FakeRunner('[{"dst":"default","gateway":"10.0.0.1","dev":"ppp0","table":"main","metric":50}]'))
    routes = manager.list_routes()
    assert routes[0].destination == "default"
    assert routes[0].gateway == "10.0.0.1"
    assert routes[0].device == "ppp0"
