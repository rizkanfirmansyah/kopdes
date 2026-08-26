from __future__ import annotations

import json
import logging
import shutil

from kopdes.application.dtos.runtime_state import ActionResult, RouteEntry, RuleEntry
from kopdes.infrastructure.system.command_runner import CommandRunner, CommandResult


LOGGER = logging.getLogger(__name__)


class RouteManager:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner

    def list_routes(self) -> list[RouteEntry]:
        if shutil.which("ip") is None:
            return []
        result = self._command_runner.run(["ip", "-j", "route", "show", "table", "all"], timeout=20)
        if result.return_code != 0:
            return []
        try:
            payload = json.loads(result.stdout or "[]")
        except (json.JSONDecodeError, TypeError):
            LOGGER.exception("Could not parse ip route output")
            return []
        if not isinstance(payload, list):
            return []
        routes: list[RouteEntry] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
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
        try:
            payload = json.loads(result.stdout or "[]")
        except (json.JSONDecodeError, TypeError):
            LOGGER.exception("Could not parse ip rule output")
            return []
        if not isinstance(payload, list):
            return []
        rules: list[RuleEntry] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
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
        if not destination.strip() or any(char in destination for char in "\r\n"):
            return ActionResult(False, "Route destination is invalid.")
        command = ["ip", "route", "add", destination.strip()]
        if gateway:
            command.extend(["via", gateway.strip()])
        if device:
            command.extend(["dev", device.strip()])
        if metric is not None:
            command.extend(["metric", str(metric)])
        if table:
            command.extend(["table", table.strip()])
        result = self._run_privileged(command, timeout=20)
        if result.return_code != 0:
            return ActionResult(False, "Failed to add route.", self._result_detail(result))
        return ActionResult(True, f"Added route '{destination}'.", self._result_detail(result))

    def delete_route(self, destination: str, table: str | None = None) -> ActionResult:
        if not destination.strip() or any(char in destination for char in "\r\n"):
            return ActionResult(False, "Route destination is invalid.")
        command = ["ip", "route", "del", destination.strip()]
        if table:
            command.extend(["table", table.strip()])
        result = self._run_privileged(command, timeout=20)
        if result.return_code != 0:
            return ActionResult(False, "Failed to delete route.", self._result_detail(result))
        return ActionResult(True, f"Deleted route '{destination}'.", self._result_detail(result))

    def change_metric(
        self,
        destination: str,
        metric: int,
        gateway: str | None = None,
        device: str | None = None,
        table: str | None = None,
    ) -> ActionResult:
        if not destination.strip() or any(char in destination for char in "\r\n"):
            return ActionResult(False, "Route destination is invalid.")
        command = ["ip", "route", "replace", destination.strip()]
        if gateway:
            command.extend(["via", gateway.strip()])
        if device:
            command.extend(["dev", device.strip()])
        command.extend(["metric", str(metric)])
        if table:
            command.extend(["table", table.strip()])
        result = self._run_privileged(command, timeout=20)
        if result.return_code != 0:
            return ActionResult(False, "Failed to change route metric.", self._result_detail(result))
        return ActionResult(True, f"Updated route metric for '{destination}'.", self._result_detail(result))

    def _run_privileged(self, command: list[str], timeout: int) -> CommandResult:
        runner = getattr(self._command_runner, "run_privileged", None)
        if runner is None:
            return self._command_runner.run(command, timeout=timeout)
        try:
            return runner(command, timeout=timeout, interactive=True)
        except TypeError:
            return runner(command, timeout=timeout)

    def _result_detail(self, result: CommandResult) -> str:
        return result.stderr.strip() or result.stdout.strip()
