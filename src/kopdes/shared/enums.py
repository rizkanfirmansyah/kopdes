from __future__ import annotations

from enum import StrEnum


class ProtocolType(StrEnum):
    OPENVPN = "openvpn"
    PPP = "ppp"
    PPTP = "pptp"
    L2TP = "l2tp"
    L2TP_IPSEC = "l2tp-ipsec"
    PPPOE = "pppoe"
    WIREGUARD = "wireguard"
    SSTP = "sstp"
    IPIP = "ipip"
    GRE = "gre"
    OPENCONNECT = "openconnect"
    SOFTETHER = "softether"


class ConnectionStatus(StrEnum):
    INACTIVE = "inactive"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISCONNECTING = "disconnecting"


class HealthCheckType(StrEnum):
    PING = "ping"
    TCP = "tcp"
    HTTP = "http"
    DNS = "dns"


class RouteMode(StrEnum):
    DEFAULT = "default"
    SPLIT = "split"
    FULL = "full"
    POLICY = "policy"


class EventLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
