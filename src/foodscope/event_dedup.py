"""Same-run and seven-day event deduplication."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
import html
import json
from pathlib import Path
import unicodedata
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
        merged.append(_merge_event_group(grouped[event_key]))
    return merged + unkeyed


def _merge_event_group(
    candidates: list[ContentItem],
) -> ContentItem:
    ordered = sorted(
        candidates,
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
    primary = ordered[0]
    assert primary.food is not None
    event_sources: list[dict] = []
    seen_sources: set[tuple[str, str]] = set()
    for candidate in ordered:
        if candidate.food is None:
            continue
        existing = candidate.metadata.get("event_sources")
        sources = (
            existing
            if isinstance(existing, list) and existing
            else [
                {
                    "source_id": candidate.food.source_id,
                    "title": candidate.title,
                    "url": str(candidate.url),
                    "language": candidate.metadata.get("language"),
                }
            ]
        )
        for source in sources:
            if not isinstance(source, dict):
                continue
            identity = (
                str(source.get("source_id", "")),
                str(source.get("url", "")),
            )
            if identity in seen_sources:
                continue
            seen_sources.add(identity)
            event_sources.append(source)
    primary.metadata["event_sources"] = event_sources
    primary.food.evidence_urls = sorted(
        {
            url
            for candidate in ordered
            if candidate.food is not None
            for url in (
                candidate.food.evidence_urls
                + [str(candidate.url)]
            )
        }
    )
    primary.food.official_evidence_urls = sorted(
        {
            url
            for candidate in ordered
            if candidate.food is not None
            for url in candidate.food.official_evidence_urls
        }
    )
    if len(ordered) > 1:
        primary.metadata["foodscope_semantic_duplicate_count"] = (
            len(event_sources) - 1
        )
    return primary


def _normalized_token(value: object) -> str:
    text = html.unescape(str(value))
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _normalized_tags(values: list[str]) -> set[str]:
    return {
        normalized
        for value in values
        if (normalized := _normalized_token(value))
    }


def _similar_food_event(
    left: ContentItem, right: ContentItem
) -> bool:
    if left.food is None or right.food is None:
        return False
    if abs(left.published_at - right.published_at) > timedelta(hours=48):
        return False
    left_markets = {market.upper() for market in left.food.markets}
    right_markets = {market.upper() for market in right.food.markets}
    if not left_markets.intersection(right_markets):
        return False
    left_companies = _normalized_tags(left.food.company_tags)
    right_companies = _normalized_tags(right.food.company_tags)
    if not left_companies.intersection(right_companies):
        return False
    left_subjects = _normalized_tags(
        left.food.product_tags
        + left.food.ingredient_tags
        + left.food.technology_tags
    )
    right_subjects = _normalized_tags(
        right.food.product_tags
        + right.food.ingredient_tags
        + right.food.technology_tags
    )
    if not left_subjects.intersection(right_subjects):
        return False
    left_title = _normalized_token(
        left.metadata.get("title_zh") or left.title
    )
    right_title = _normalized_token(
        right.metadata.get("title_zh") or right.title
    )
    return (
        SequenceMatcher(None, left_title, right_title).ratio()
        >= 0.4
    )


def merge_similar_food_events(
    items: list[ContentItem],
) -> list[ContentItem]:
    """Merge semantically matching events after structured AI analysis."""

    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if _similar_food_event(items[left], items[right]):
                union(left, right)

    groups: dict[int, list[ContentItem]] = defaultdict(list)
    for index, item in enumerate(items):
        groups[find(index)].append(item)
    return [
        _merge_event_group(group)
        if all(item.food is not None for item in group)
        else group[0]
        for group in groups.values()
    ]


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
