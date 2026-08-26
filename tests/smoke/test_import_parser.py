from pathlib import Path

from kopdes.infrastructure.system.config_parser import ConfigImportParser


def test_import_parser_reads_ovpn_style_text(tmp_path: Path) -> None:
    config = tmp_path / "sample.ovpn"
    config.write_text("remote vpn.example.net 1194\nproto udp\n", encoding="utf-8")
    payload = ConfigImportParser().parse(config)
    assert payload["server_address"] == "vpn.example.net"
    assert payload["port"] == 1194
