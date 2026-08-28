from __future__ import annotations

import json
import logging
import shutil
from threading import RLock
from time import monotonic

from kopdes.application.dtos.runtime_state import ActionResult, RouteEntry, RuleEntry
from kopdes.infrastructure.system.command_runner import CommandRunner, CommandResult


LOGGER = logging.getLogger(__name__)


class RouteManager:
    CACHE_WINDOW_SECONDS = 0.5

    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner
        self._lock = RLock()
        self._routes_cache: tuple[float, list[RouteEntry]] | None = None
        self._rules_cache: tuple[float, list[RuleEntry]] | None = None

    def list_routes(self) -> list[RouteEntry]:
        with self._lock:
            now = monotonic()
            if self._routes_cache and now - self._routes_cache[0] < self.CACHE_WINDOW_SECONDS:
                return list(self._routes_cache[1])
            routes = self._read_routes()
            self._routes_cache = (now, routes)
            return list(routes)

    def list_rules(self) -> list[RuleEntry]:
        with self._lock:
            now = monotonic()
            if self._rules_cache and now - self._rules_cache[0] < self.CACHE_WINDOW_SECONDS:
                return list(self._rules_cache[1])
            rules = self._read_rules()
            self._rules_cache = (now, rules)
            return list(rules)

    def add_route(
        self,
        destination: str,
        gateway: str | None = None,
        device: str | None = None,
        metric: int | None = None,
        table: str | None = None,
    ) -> ActionResult:
        validation_error = self._validate_route_input(destination, gateway, device, table, metric)
        if validation_error:
            return ActionResult(False, validation_error)
        with self._lock:
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
            self._invalidate_cache()
            return ActionResult(True, f"Added route '{destination}'.", self._result_detail(result))

    def delete_route(self, destination: str, table: str | None = None) -> ActionResult:
        validation_error = self._validate_route_input(destination, table=table)
        if validation_error:
            return ActionResult(False, validation_error)
        with self._lock:
            command = ["ip", "route", "del", destination.strip()]
            if table:
                command.extend(["table", table.strip()])
            result = self._run_privileged(command, timeout=20)
            if result.return_code != 0:
                return ActionResult(False, "Failed to delete route.", self._result_detail(result))
            self._invalidate_cache()
            return ActionResult(True, f"Deleted route '{destination}'.", self._result_detail(result))

    def change_metric(
        self,
        destination: str,
        metric: int,
        gateway: str | None = None,
        device: str | None = None,
        table: str | None = None,
    ) -> ActionResult:
        validation_error = self._validate_route_input(destination, gateway, device, table, metric)
        if validation_error:
            return ActionResult(False, validation_error)
        with self._lock:
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
            self._invalidate_cache()
            return ActionResult(True, f"Updated route metric for '{destination}'.", self._result_detail(result))

    def _read_routes(self) -> list[RouteEntry]:
        if shutil.which("ip") is None:
            return []
        result = self._command_runner.run(
            ["ip", "-j", "route", "show", "table", "all"],
            timeout=20,
        )
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

    def _read_rules(self) -> list[RuleEntry]:
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

    def _validate_route_input(
        self,
        destination: str,
        gateway: str | None = None,
        device: str | None = None,
        table: str | None = None,
        metric: int | None = None,
    ) -> str | None:
        if not self._valid_token(destination):
            return "Route destination is invalid."
        for label, value in (("Gateway", gateway), ("Device", device), ("Route table", table)):
            if value is not None and not self._valid_token(value):
                return f"{label} is invalid."
        if metric is not None:
            try:
                if not 1 <= int(metric) <= 9999:
                    return "Route metric must be between 1 and 9999."
            except (TypeError, ValueError):
                return "Route metric must be between 1 and 9999."
        return None

    def _valid_token(self, value: str | None) -> bool:
        if value is None:
            return True
        text = str(value).strip()
        return bool(text) and not any(char.isspace() or ord(char) < 32 for char in text)

    def _invalidate_cache(self) -> None:
        self._routes_cache = None
        self._rules_cache = None

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
