"""Safely resolve aggregator links to their publisher URLs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
import ipaddress
import socket
from typing import Awaitable, Callable, Literal
from urllib.parse import urljoin, urlsplit

import httpx
import tldextract

from src.models import ContentItem


ResolutionStatus = Literal[
    "resolved", "fallback", "failed", "disabled"
]
HostResolver = Callable[[str], Awaitable[list[str]]]

_AGGREGATOR_HOSTS = {"news.google.com"}
_EXTRACT_DOMAIN = tldextract.TLDExtract(
    cache_dir=None,
    suffix_list_urls=(),
)


@dataclass(frozen=True)
class OriginalUrlResolution:
    status: ResolutionStatus
    url: str | None = None
    publisher_domain: str | None = None
    error: str | None = None


class _CanonicalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.candidate: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self.candidate is not None:
            return
        values = {
            key.lower(): (value or "")
            for key, value in attrs
        }
        if (
            tag.lower() == "link"
            and "canonical" in values.get("rel", "").lower().split()
        ):
            self.candidate = values.get("href") or None
        elif (
            tag.lower() == "meta"
            and values.get("property", "").lower() == "og:url"
        ):
            self.candidate = values.get("content") or None


class OriginalUrlResolver:
    """Resolve redirects without allowing requests to private targets."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        enabled: bool = True,
        max_redirects: int = 5,
        timeout_seconds: float = 5.0,
        max_body_bytes: int = 262_144,
        max_concurrency: int = 4,
        host_resolver: HostResolver | None = None,
    ):
        self.client = client
        self.enabled = enabled
        self.max_redirects = max_redirects
        self.timeout_seconds = timeout_seconds
        self.max_body_bytes = max_body_bytes
        self._host_resolver = (
            host_resolver or self._resolve_host_addresses
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[
            str, asyncio.Task[OriginalUrlResolution]
        ] = {}

    async def resolve(self, url: str) -> OriginalUrlResolution:
        if not self.enabled:
            return OriginalUrlResolution(status="disabled")
        if not self._is_aggregator(url):
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                error = "unsupported_aggregator"
            else:
                error = (
                    "unsupported_aggregator"
                    if literal.is_global
                    else "unsafe_target"
                )
            return OriginalUrlResolution(
                status="failed", error=error
            )
        task = self._tasks.get(url)
        if task is None:
            task = asyncio.create_task(self._resolve(url))
            self._tasks[url] = task
        return await asyncio.shield(task)

    async def resolve_items(
        self,
        items: list[ContentItem],
        *,
        allow_aggregator_fallback: bool,
    ) -> None:
        async def one(item: ContentItem) -> None:
            existing = str(
                item.metadata.get("resolved_original_url") or ""
            ).strip()
            if existing:
                result = self._resolved(existing)
            elif (
                item.metadata.get("discovery_provider")
                != "google_news"
            ):
                return
            else:
                try:
                    result = await self.resolve(str(item.url))
                except Exception:
                    result = OriginalUrlResolution(
                        status="failed", error="unexpected_error"
                    )
            status: ResolutionStatus = result.status
            publisher = str(
                item.metadata.get("discovered_source_name") or ""
            ).strip()
            if (
                status == "failed"
                and allow_aggregator_fallback
                and publisher
            ):
                status = "fallback"
            item.metadata["original_url_resolution_status"] = (
                status
            )
            if result.error is not None:
                item.metadata["original_url_resolution_error"] = (
                    result.error
                )
            if result.url is not None:
                item.metadata["resolved_original_url"] = result.url
            if result.publisher_domain is not None:
                item.metadata["publisher_domain"] = (
                    result.publisher_domain
                )

        await asyncio.gather(*(one(item) for item in items))

    async def _resolve(
        self, url: str
    ) -> OriginalUrlResolution:
        async with self._semaphore:
            current = url
            for redirect_count in range(
                self.max_redirects + 1
            ):
                if not self._is_aggregator(current):
                    return OriginalUrlResolution(
                        status="failed",
                        error="unsupported_aggregator",
                    )
                try:
                    async with self.client.stream(
                        "GET",
                        current,
                        follow_redirects=False,
                        timeout=self.timeout_seconds,
                        headers={
                            "accept": "text/html,application/xhtml+xml"
                        },
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                return OriginalUrlResolution(
                                    status="failed",
                                    error="redirect_without_location",
                                )
                            if redirect_count >= self.max_redirects:
                                return OriginalUrlResolution(
                                    status="failed",
                                    error="too_many_redirects",
                                )
                            candidate = urljoin(current, location)
                            if not self._is_aggregator(candidate):
                                if await self._is_public_url(
                                    candidate
                                ):
                                    return self._resolved(candidate)
                                return OriginalUrlResolution(
                                    status="failed",
                                    error="unsafe_target",
                                )
                            current = candidate
                            continue
                        if response.status_code >= 400:
                            return OriginalUrlResolution(
                                status="failed",
                                error=f"http_{response.status_code}",
                            )
                        if not self._is_aggregator(current):
                            return self._resolved(current)
                        body = await self._bounded_body(response)
                except httpx.HTTPError:
                    return OriginalUrlResolution(
                        status="failed", error="request_failed"
                    )

                candidate = self._canonical_url(body, current)
                if (
                    candidate is not None
                    and not self._is_aggregator(candidate)
                ):
                    if await self._is_public_url(candidate):
                        return self._resolved(candidate)
                    return OriginalUrlResolution(
                        status="failed", error="unsafe_target"
                    )
                return OriginalUrlResolution(
                    status="failed", error="original_url_not_found"
                )
            return OriginalUrlResolution(
                status="failed", error="too_many_redirects"
            )

    async def _bounded_body(
        self, response: httpx.Response
    ) -> bytes:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            remaining = self.max_body_bytes - len(body)
            if remaining <= 0:
                break
            body.extend(chunk[:remaining])
            if len(chunk) > remaining:
                break
        return bytes(body)

    @staticmethod
    def _canonical_url(body: bytes, base_url: str) -> str | None:
        parser = _CanonicalParser()
        parser.feed(body.decode("utf-8", errors="ignore"))
        if parser.candidate is None:
            return None
        candidate = urljoin(base_url, parser.candidate.strip())
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"}:
            return None
        return candidate

    @staticmethod
    def _is_aggregator(url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower()
            in _AGGREGATOR_HOSTS
        )

    @staticmethod
    def _resolved(url: str) -> OriginalUrlResolution:
        extracted = _EXTRACT_DOMAIN(url)
        domain = (
            extracted.top_domain_under_public_suffix
            or extracted.domain
            or None
        )
        return OriginalUrlResolution(
            status="resolved",
            url=url,
            publisher_domain=domain.lower() if domain else None,
        )

    async def _is_public_url(self, url: str) -> bool:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.hostname
        ):
            return False
        host = parsed.hostname.lower().rstrip(".")
        if (
            host == "localhost"
            or host.endswith(".localhost")
            or host.endswith(".local")
        ):
            return False
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            try:
                addresses = await asyncio.wait_for(
                    self._host_resolver(host),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                return False
            if not addresses:
                return False
            try:
                return all(
                    ipaddress.ip_address(address).is_global
                    for address in addresses
                )
            except ValueError:
                return False
        return literal.is_global

    @staticmethod
    async def _resolve_host_addresses(host: str) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            results = await loop.getaddrinfo(
                host, None, type=socket.SOCK_STREAM
            )
        except OSError:
            return []
        return sorted(
            {
                str(sockaddr[0])
                for _family, _type, _proto, _canon, sockaddr in results
            }
        )
