from kopdes.infrastructure.system.interface_monitor import InterfaceMonitor


def test_interface_monitor_classifies_known_tunnel_prefixes() -> None:
    monitor = InterfaceMonitor()
    assert monitor._classify("tun0") == "tun"
    assert monitor._classify("tap5") == "tap"
    assert monitor._classify("ppp1") == "ppp"
