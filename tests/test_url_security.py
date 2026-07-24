from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.url_security import UnsafeURLError, safe_request, validate_public_http_url


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://192.0.2.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::]/",
        "http://[ff02::1]/",
        "http://[2001:db8::1]/",
    ],
)
def test_rejects_non_public_ip_destinations(url):
    with pytest.raises(UnsafeURLError, match="non-public"):
        _run(validate_public_http_url(url))


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "https://service.localhost./hook",
        "ftp://example.com/file",
        "https://user:secret@example.com/hook",
    ],
)
def test_rejects_unsafe_url_forms(url):
    with pytest.raises(UnsafeURLError):
        _run(validate_public_http_url(url))


def test_rejects_hostname_when_any_resolved_ip_is_private():
    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34", "10.0.0.2"}),
    ):
        with pytest.raises(UnsafeURLError, match="10.0.0.2"):
            _run(validate_public_http_url("https://example.com/hook"))


def test_accepts_public_ipv4_and_ipv6_dns_answers():
    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"}),
    ):
        assert _run(validate_public_http_url("https://example.com/hook"))


def test_redirect_is_validated_before_second_request():
    redirect = MagicMock(
        status_code=302,
        headers={"location": "http://127.0.0.1/admin"},
    )
    client = MagicMock()
    client.get = AsyncMock(return_value=redirect)

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(side_effect=[{"93.184.216.34"}, {"127.0.0.1"}]),
    ):
        with pytest.raises(UnsafeURLError, match="non-public"):
            _run(safe_request(client, "GET", "https://example.com/start"))

    client.get.assert_awaited_once_with(
        "https://example.com/start", follow_redirects=False
    )


def test_public_relative_redirect_is_followed():
    redirect = MagicMock(status_code=301, headers={"location": "/next"})
    success = MagicMock(status_code=200, headers={})
    client = MagicMock()
    client.get = AsyncMock(side_effect=[redirect, success])

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34"}),
    ):
        result = _run(safe_request(client, "GET", "https://example.com/start"))

    assert result is success
    assert client.get.await_args_list[1].args == ("https://example.com/next",)
    assert client.get.await_args_list[1].kwargs == {"follow_redirects": False}
