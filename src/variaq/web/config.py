"""Configuration for the VariaQ local web server."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

#: Loopback-only is the security default for the local-first 0.7 UI. This value
#: is covered by a regression test; do not change it to a public bind address.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8701
DEFAULT_REPORTS_DIR = Path("data/reports")


def is_loopback_host(host: str) -> bool:
    """True when a host string refers to this machine only."""
    value = host.strip().lower()
    if value in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        pass
    # IPv6 textual forms with brackets, e.g. "[::1]"
    try:
        return ipaddress.ip_address(value.strip("[]")).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class WebConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    db_path: Path = Path("data/variaq.sqlite3")
    problems_dir: Path = Path("data/problems")
    reports_dir: Path = DEFAULT_REPORTS_DIR

    @property
    def bind_is_loopback(self) -> bool:
        return is_loopback_host(self.host)

    def remote_bind_warning(self) -> str | None:
        if self.bind_is_loopback:
            return None
        return (
            f"WARNING: VariaQ web UI is binding to non-loopback address {self.host}. "
            "This interface provides no hardened authentication/authorization and is "
            "intended for the local machine or a trusted lab network only. Do NOT "
            "expose it to the public internet."
        )
