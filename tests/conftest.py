from __future__ import annotations

import sys
from pathlib import Path
import socket

import pytest


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def resolve_reserved_test_domains(monkeypatch):
    """Keep HTTP unit tests offline while still exercising SSRF checks."""

    original = socket.getaddrinfo

    def deterministic_getaddrinfo(
        host,
        port,
        family=0,
        type=0,
        proto=0,
        flags=0,
    ):
        normalized = str(host).rstrip(".").lower()
        if (
            normalized == "example.com"
            or normalized == "new-url.com"
            or normalized.endswith(".example")
            or normalized.endswith(".test")
        ):
            return [
                (
                    socket.AF_INET,
                    type or socket.SOCK_STREAM,
                    proto,
                    "",
                    ("93.184.216.34", port),
                )
            ]
        return original(
            host,
            port,
            family,
            type,
            proto,
            flags,
        )

    monkeypatch.setattr(
        "src.url_security.socket.getaddrinfo",
        deterministic_getaddrinfo,
    )
