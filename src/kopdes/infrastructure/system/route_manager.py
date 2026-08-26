from __future__ import annotations

import json
import shutil

from kopdes.application.dtos.runtime_state import ActionResult, RouteEntry, RuleEntry
from kopdes.infrastructure.system.command_runner import CommandRunner


class RouteManager:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner

    def list_routes(self) -> list[RouteEntry]:
        if shutil.which("ip") is None:
            return []
        result = self._command_runner.run(["ip", "-j", "route", "show", "table", "all"], timeout=20)
        if result.return_code != 0:
            return []
        payload = json.loads(result.stdout or "[]")
        routes: list[RouteEntry] = []
        for item in payload:
            routes.append(
                RouteEntry(
                    destination=item.get("dst", "default"),
                    gateway=item.get("gateway"),
                    device=item.get("dev"),
                    table=str(item.get("table", "main")),
                    metric=item.get("metric"),
                    source=item.get("prefsrc"),
                    protocol=item.get("protocol"),
                    scope=item.get("scope"),
                )
            )
        return routes

    def list_rules(self) -> list[RuleEntry]:
        if shutil.which("ip") is None:
            return []
        result = self._command_runner.run(["ip", "-j", "rule", "show"], timeout=20)
        if result.return_code != 0:
            return []
        payload = json.loads(result.stdout or "[]")
        rules: list[RuleEntry] = []
        for item in payload:
            rules.append(
                RuleEntry(
                    priority=item.get("priority"),
                    table=str(item.get("table")) if item.get("table") is not None else None,
                    source=item.get("from"),
                    destination=item.get("to"),
                    action=item.get("action"),
                )
            )
        return rules

    def add_route(
        self,
        destination: str,
        gateway: str | None = None,
        device: str | None = None,
        metric: int | None = None,
        table: str | None = None,
    ) -> ActionResult:
        command = ["ip", "route", "add", destination]
        if gateway:
            command.extend(["via", gateway])
        if device:
            command.extend(["dev", device])
        if metric is not None:
            command.extend(["metric", str(metric)])
        if table:
            command.extend(["table", table])
        result = self._command_runner.run(command, timeout=20)
        if result.return_code != 0:
            return ActionResult(False, "Failed to add route.", result.stderr.strip())
        return ActionResult(True, f"Added route '{destination}'.", result.stdout.strip())

    def delete_route(self, destination: str, table: str | None = None) -> ActionResult:
        command = ["ip", "route", "del", destination]
        if table:
            command.extend(["table", table])
        result = self._command_runner.run(command, timeout=20)
        if result.return_code != 0:
            return ActionResult(False, "Failed to delete route.", result.stderr.strip())
        return ActionResult(True, f"Deleted route '{destination}'.", result.stdout.strip())

    def change_metric(
        self,
        destination: str,
        metric: int,
        gateway: str | None = None,
        device: str | None = None,
        table: str | None = None,
    ) -> ActionResult:
        command = ["ip", "route", "replace", destination]
        if gateway:
            command.extend(["via", gateway])
        if device:
            command.extend(["dev", device])
        command.extend(["metric", str(metric)])
        if table:
            command.extend(["table", table])
        result = self._command_runner.run(command, timeout=20)
        if result.return_code != 0:
            return ActionResult(False, "Failed to change route metric.", result.stderr.strip())
        return ActionResult(True, f"Updated route metric for '{destination}'.", result.stdout.strip())
