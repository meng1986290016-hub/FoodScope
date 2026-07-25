"""Same-run and seven-day event deduplication."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src._file_utils import _atomic_write_text
from src.models import ContentItem


_TRACKING_QUERY_KEYS = {
    "dclid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}


def canonical_url_event_key(url: str) -> str:
    """Return a stable fallback key after removing tracking decoration."""

    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(
                parsed.query, keep_blank_values=True
            )
            if not key.lower().startswith("utm_")
            and key.lower() not in _TRACKING_QUERY_KEYS
        ),
        doseq=True,
    )
    path = parsed.path.rstrip("/") or "/"
    canonical = urlunsplit((scheme, hostname, path, query, ""))
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"url:{digest}"


def merge_food_events(items: list[ContentItem]) -> list[ContentItem]:
    """Merge cross-language items that share a canonical event key."""

    grouped: dict[str, list[ContentItem]] = defaultdict(list)
    unkeyed: list[ContentItem] = []
    for item in items:
        if item.food and item.food.event_key:
            grouped[item.food.event_key].append(item)
        else:
            unkeyed.append(item)

    merged: list[ContentItem] = []
    for event_key in sorted(grouped):
        candidates = sorted(
            grouped[event_key],
            key=lambda candidate: (
                candidate.food.evidence_tier if candidate.food else 99,
                -(
                    candidate.food.evidence_quality_score
                    if candidate.food
                    else 0
                ),
                str(candidate.url),
            ),
        )
        primary = candidates[0]
        assert primary.food is not None
        primary.metadata["event_sources"] = [
            {
                "source_id": candidate.food.source_id,
                "title": candidate.title,
                "url": str(candidate.url),
                "language": candidate.metadata.get("language"),
            }
            for candidate in candidates
            if candidate.food is not None
        ]
        primary.food.evidence_urls = sorted(
            set(
                primary.food.evidence_urls
                + [str(candidate.url) for candidate in candidates]
            )
        )
        primary.food.official_evidence_urls = sorted(
            {
                url
                for candidate in candidates
                if candidate.food is not None
                for url in candidate.food.official_evidence_urls
            }
        )
        merged.append(primary)
    return merged + unkeyed


class FoodEventFingerprintStore:
    """Persist admitted event keys for a rolling seven-day window."""

    def __init__(self, path: Path, retention_days: int = 7):
        self.path = path
        self.retention = timedelta(days=retention_days)

    def filter_new(
        self, items: list[ContentItem], now: datetime | None = None
    ) -> list[ContentItem]:
        """Return items not admitted within the active retention window."""

        active = self._load_active(now or datetime.now(timezone.utc))
        return [
            item
            for item in items
            if not item.food
            or not item.food.event_key
            or item.food.event_key not in active
        ]

    def remember(
        self, items: list[ContentItem], now: datetime | None = None
    ) -> None:
        """Atomically remember admitted, non-isolated event keys."""

        observed_at = now or datetime.now(timezone.utc)
        active = self._load_active(observed_at)
        for item in items:
            if (
                item.food
                and item.food.event_key
                and not item.metadata.get("foodscope_isolated")
                and not item.metadata.get("foodscope_evidence_rejected")
            ):
                active[item.food.event_key] = observed_at.isoformat()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            active,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        _atomic_write_text(self.path, f"{content}\n")

    def _load_active(self, now: datetime) -> dict[str, str]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        cutoff = now - self.retention
        active: dict[str, str] = {}
        for event_key, raw_timestamp in payload.items():
            timestamp = datetime.fromisoformat(raw_timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp >= cutoff:
                active[event_key] = timestamp.isoformat()
        return active
