from __future__ import annotations

import json
from pathlib import Path

import yaml

from kopdes.shared.enums import ProtocolType


class ConfigImportParser:
    MAX_CONFIG_BYTES = 2 * 1024 * 1024

    def parse(self, path: Path) -> dict[str, object]:
        suffix = path.suffix.lower()
        try:
            size = path.stat().st_size
            if size > self.MAX_CONFIG_BYTES:
                raise ValueError(
                    f"Configuration file is too large ({size} bytes); "
                    f"maximum is {self.MAX_CONFIG_BYTES} bytes."
                )
            raw = path.read_bytes().decode("utf-8", errors="replace")
        except OSError as exc:
            raise ValueError(f"Configuration file could not be read: {exc}") from exc
        if not raw.strip():
            raise ValueError("Configuration file is empty.")
        try:
            if suffix == ".json":
                payload = json.loads(raw)
                return self._normalize_mapping(payload)
            if suffix in {".yaml", ".yml"}:
                payload = yaml.safe_load(raw) or {}
                return self._normalize_mapping(payload)
            return self._parse_text(raw)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise ValueError(f"Configuration file could not be parsed: {exc}") from exc

    def _normalize_mapping(self, payload: dict[str, object]) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("Structured configuration must contain an object/map at its root.")
        server_address = payload.get("server") or payload.get("server_address", "")
        protocol = str(payload.get("protocol", ProtocolType.OPENVPN.value))
        warnings: list[str] = []
        errors: list[str] = []
        if not server_address:
            errors.append("Server address is missing.")
        return {
            "name": payload.get("name", "Imported Profile"),
            "server_address": server_address,
            "port": payload.get("port"),
            "protocol": protocol,
            "username": payload.get("username"),
            "description": payload.get("description", "Imported configuration"),
            "config_payload": payload,
            "warnings": warnings,
            "errors": errors,
        }

    def _parse_text(self, raw: str) -> dict[str, object]:
        protocol = ProtocolType.OPENVPN.value
        interface_name = ""
        remote = ""
        port = None
        username = None
        auth_user_pass_required = False
        auth_user_pass_file = ""
        warnings: list[str] = []
        errors: list[str] = []
        has_client = False
        for line in raw.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue
            if stripped == "client":
                has_client = True
            if "wireguard" in lower:
                protocol = ProtocolType.WIREGUARD.value
            elif "pppoe" in lower:
                protocol = ProtocolType.PPPOE.value
            elif "l2tp" in lower:
                protocol = ProtocolType.L2TP.value
            elif stripped.startswith("remote "):
                parts = stripped.split()
                if len(parts) >= 2:
                    remote = parts[1]
                if len(parts) >= 3 and parts[2].isdigit():
                    port = int(parts[2])
            elif stripped.startswith("proto "):
                value = stripped.split(maxsplit=1)[1].lower()
                if value in {item.value for item in ProtocolType}:
                    protocol = value
            elif stripped.startswith("dev "):
                interface_name = stripped.split(maxsplit=1)[1]
            elif stripped.startswith("auth-user-pass"):
                parts = stripped.split(maxsplit=1)
                auth_user_pass_required = True
                if len(parts) == 2:
                    auth_user_pass_file = parts[1].strip()
            elif stripped.startswith("setenv CLIENT_CERT 0"):
                username = None

        if protocol == ProtocolType.OPENVPN.value and not has_client:
            warnings.append("OpenVPN file does not declare 'client'.")
        if not remote:
            errors.append("Remote server address is missing from the configuration file.")
        if not interface_name:
            warnings.append("Tunnel device is not declared explicitly; KOPDES will detect it at runtime.")

        config_payload: dict[str, object] = {"raw": raw}
        if interface_name:
            config_payload["interface_name"] = interface_name
        if auth_user_pass_required:
            config_payload["auth_user_pass_required"] = True
        if auth_user_pass_file:
            config_payload["auth_user_pass_file"] = auth_user_pass_file
        return {
            "name": "Imported Profile",
            "server_address": remote,
            "port": port,
            "protocol": protocol,
            "username": username,
            "description": "Imported configuration",
            "config_payload": config_payload,
            "warnings": warnings,
            "errors": errors,
        }
