"""Same-run and seven-day event deduplication."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
import html
import json
from pathlib import Path
import re
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

_DEFAULT_SEMANTIC_WINDOW = timedelta(hours=48)
_COMPANY_STOP_WORDS = {
    "and",
    "co",
    "company",
    "corp",
    "corporation",
    "group",
    "holdings",
    "inc",
    "limited",
    "ltd",
    "of",
    "plc",
    "the",
}
_METRIC_PATTERN = re.compile(
    r"(?<![\d.])"
    r"(?P<number>\d+(?:\.\d+)?)"
    r"\s*"
    r"(?P<unit>%|％|亿|万|千|trillion|billion|million|bn|mn)",
    re.IGNORECASE,
)
_METRIC_UNIT_ALIASES = {
    "％": "%",
    "bn": "billion",
    "mn": "million",
}
_EVENT_KIND_KEYWORDS = {
    "acquisition": (
        "收购",
        "出售",
        "并购",
        "acquisition",
        "acquire",
        "divest",
        "sale",
    ),
    "capacity": (
        "产能",
        "产线",
        "生产线",
        "工厂",
        "投产",
        "扩产",
        "扩建",
        "capacity",
        "facility",
        "factory",
        "productionline",
    ),
    "financial_performance": (
        "业绩",
        "财报",
        "季度",
        "销量",
        "销售额",
        "收入",
        "利润",
        "指引",
        "earnings",
        "guidance",
        "profit",
        "revenue",
        "sales",
        "volume",
    ),
    "investment": (
        "融资",
        "投资",
        "funding",
        "investment",
    ),
    "launch": (
        "发布",
        "推出",
        "上市",
        "launch",
        "release",
    ),
    "pricing": (
        "价格",
        "提价",
        "涨价",
        "priceincrease",
        "pricing",
    ),
    "recall": (
        "召回",
        "recall",
    ),
    "recycling": (
        "回收",
        "再生",
        "recycling",
        "recycled",
    ),
    "research": (
        "专利",
        "技术",
        "研究",
        "突破",
        "patent",
        "research",
        "technology",
    ),
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


def _normalized_company_tags(values: list[str]) -> set[str]:
    """Add stable Latin-script cores and acronyms for company aliases."""

    normalized = _normalized_tags(values)
    for value in values:
        ascii_words = re.findall(
            r"[a-z0-9]+",
            unicodedata.normalize("NFKC", value).casefold(),
        )
        core_words = [
            word
            for word in ascii_words
            if word not in _COMPANY_STOP_WORDS
        ]
        if core_words:
            core = "".join(core_words)
            if len(core) >= 4:
                normalized.add(core)
        if len(core_words) >= 2:
            acronym = "".join(word[0] for word in core_words)
            if 3 <= len(acronym) <= 8:
                normalized.add(acronym)
    return normalized


def _tags_overlap(
    left: set[str],
    right: set[str],
    *,
    fuzzy_threshold: float | None = None,
) -> bool:
    """Match exact tags plus common cross-language alias expansions."""

    if left.intersection(right):
        return True
    if any(
        min(len(left_tag), len(right_tag)) >= 2
        and (
            left_tag in right_tag
            or right_tag in left_tag
        )
        for left_tag in left
        for right_tag in right
    ):
        return True
    if fuzzy_threshold is None:
        return False
    return any(
        min(len(left_tag), len(right_tag)) >= 4
        and SequenceMatcher(None, left_tag, right_tag).ratio()
        >= fuzzy_threshold
        for left_tag in left
        for right_tag in right
    )


def _metric_contexts(item: ContentItem) -> dict[str, set[str]]:
    """Return normalized context windows for explicit numeric metrics."""

    text = " ".join(
        value
        for value in (
            item.title,
            str(item.metadata.get("title_zh") or ""),
            item.ai_summary or "",
        )
        if value
    )
    contexts: dict[str, set[str]] = defaultdict(set)
    for match in _METRIC_PATTERN.finditer(text):
        number = match.group("number")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        unit = match.group("unit").casefold()
        unit = _METRIC_UNIT_ALIASES.get(unit, unit)
        signature = f"{number}{unit}"
        start = max(0, match.start() - 18)
        end = min(len(text), match.end() + 18)
        contexts[signature].add(_normalized_token(text[start:end]))
    return contexts


def _event_kinds(item: ContentItem) -> set[str]:
    text = _normalized_token(
        " ".join(
            value
            for value in (
                item.title,
                str(item.metadata.get("title_zh") or ""),
                item.ai_summary or "",
                item.food.event_key if item.food is not None else "",
            )
            if value
        )
    )
    return {
        kind
        for kind, keywords in _EVENT_KIND_KEYWORDS.items()
        if any(_normalized_token(keyword) in text for keyword in keywords)
    }


def _shared_metric_context_similarity(
    left: ContentItem,
    right: ContentItem,
) -> float:
    left_contexts = _metric_contexts(left)
    right_contexts = _metric_contexts(right)
    shared = left_contexts.keys() & right_contexts.keys()
    if not shared:
        return 0.0
    return max(
        SequenceMatcher(None, left_context, right_context).ratio()
        for signature in shared
        for left_context in left_contexts[signature]
        for right_context in right_contexts[signature]
    )


def _text_similarity(left: object, right: object) -> float:
    if not left or not right:
        return 0.0
    left_text = _normalized_token(left)
    right_text = _normalized_token(right)
    if not left_text or not right_text:
        return 0.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def _meaningful_event_key_parts(item: ContentItem) -> set[str]:
    if item.food is None or not item.food.event_key:
        return set()
    company_terms = _normalized_company_tags(
        item.food.company_tags
    )
    market_terms = {
        _normalized_token(market) for market in item.food.markets
    }
    meaningful: set[str] = set()
    for raw_part in item.food.event_key.split("|"):
        part = _normalized_token(raw_part)
        if not part or len(part) <= 2:
            continue
        if part in market_terms or part in {"global", "worldwide"}:
            continue
        if re.fullmatch(r"20\d{2}(?:\d{2}){0,2}", part):
            continue
        if _tags_overlap({part}, company_terms):
            continue
        meaningful.add(part)
    return meaningful


def _similar_food_event(
    left: ContentItem,
    right: ContentItem,
    *,
    max_age: timedelta = _DEFAULT_SEMANTIC_WINDOW,
) -> bool:
    if left.food is None or right.food is None:
        return False
    if canonical_url_event_key(str(left.url)) == canonical_url_event_key(
        str(right.url)
    ):
        return True
    event_age = abs(left.published_at - right.published_at)
    if event_age > max_age:
        return False
    left_markets = {market.upper() for market in left.food.markets}
    right_markets = {market.upper() for market in right.food.markets}
    market_match = bool(left_markets.intersection(right_markets))
    category_match = left.food.category == right.food.category
    left_companies = _normalized_company_tags(
        left.food.company_tags
    )
    right_companies = _normalized_company_tags(
        right.food.company_tags
    )
    company_match = _tags_overlap(left_companies, right_companies)
    subject_groups = (
        (
            _normalized_tags(left.food.product_tags),
            _normalized_tags(right.food.product_tags),
        ),
        (
            _normalized_tags(left.food.ingredient_tags),
            _normalized_tags(right.food.ingredient_tags),
        ),
        (
            _normalized_tags(left.food.technology_tags),
            _normalized_tags(right.food.technology_tags),
        ),
    )
    subject_match = any(
        _tags_overlap(
            left_subjects,
            right_subjects,
            fuzzy_threshold=0.65,
        )
        for left_subjects, right_subjects in subject_groups
        if left_subjects and right_subjects
    )
    left_titles = {
        _normalized_token(left.title),
        _normalized_token(left.metadata.get("title_zh") or ""),
    }
    right_titles = {
        _normalized_token(right.title),
        _normalized_token(right.metadata.get("title_zh") or ""),
    }
    left_titles.discard("")
    right_titles.discard("")
    title_similarity = max(
        SequenceMatcher(None, left_title, right_title).ratio()
        for left_title in left_titles
        for right_title in right_titles
    )
    left_preferred_title = _normalized_token(
        left.metadata.get("title_zh") or left.title
    )
    right_preferred_title = _normalized_token(
        right.metadata.get("title_zh") or right.title
    )
    preferred_title_similarity = SequenceMatcher(
        None, left_preferred_title, right_preferred_title
    ).ratio()
    summary_similarity = _text_similarity(
        left.ai_summary, right.ai_summary
    )
    left_key_parts = _meaningful_event_key_parts(left)
    right_key_parts = _meaningful_event_key_parts(right)
    key_part_match = _tags_overlap(
        left_key_parts, right_key_parts
    )
    metric_context_similarity = (
        _shared_metric_context_similarity(left, right)
    )
    left_event_kinds = _event_kinds(left)
    right_event_kinds = _event_kinds(right)
    event_kind_match = bool(
        left_event_kinds.intersection(right_event_kinds)
    )
    event_kinds_compatible = (
        not left_event_kinds
        or not right_event_kinds
        or event_kind_match
    )
    # Exact/near-exact translated headlines are strong enough even when
    # an analyzer omitted product tags (financial results are common).
    if title_similarity >= 0.9:
        return True
    # Company + subject is the most reliable structured signature.  Do
    # not require markets because discovery metadata occasionally assigns
    # the publisher's market rather than the event's market.
    if (
        company_match
        and subject_match
        and event_kinds_compatible
        and preferred_title_similarity >= 0.4
    ):
        return True
    if (
        company_match
        and subject_match
        and key_part_match
        and event_kinds_compatible
        and preferred_title_similarity >= 0.25
    ):
        return True
    # Different-language coverage can use incompatible subject tags.
    # Matching company, market, category and a distinctive metric in
    # similar context is a conservative bridge for those reports.
    metric_title_threshold = (
        0.2
        if event_age <= _DEFAULT_SEMANTIC_WINDOW
        else 0.45
    )
    if (
        company_match
        and market_match
        and category_match
        and event_kind_match
        and metric_context_similarity >= 0.2
        and (
            subject_match
            or metric_context_similarity >= 0.45
        )
        and preferred_title_similarity >= metric_title_threshold
    ):
        return True
    if (
        company_match
        and market_match
        and category_match
        and event_kinds_compatible
        and summary_similarity >= 0.6
        and preferred_title_similarity >= 0.35
    ):
        return True
    # Allow company aliases or translated brand variants when the market,
    # subject and headline still agree.
    if (
        market_match
        and subject_match
        and event_kinds_compatible
        and preferred_title_similarity >= 0.45
    ):
        return True
    return False


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
        remembered_items = [
            remembered
            for _, remembered in active.values()
            if remembered is not None
        ]
        fresh: list[ContentItem] = []
        for item in items:
            if (
                item.food
                and item.food.event_key
                and item.food.event_key in active
            ):
                continue
            if any(
                _similar_food_event(
                    item,
                    remembered,
                    max_age=self.retention,
                )
                for remembered in remembered_items
            ):
                continue
            fresh.append(item)
        return fresh

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
                active[item.food.event_key] = (observed_at, item)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            event_key: {
                "observed_at": timestamp.isoformat(),
                "item": (
                    remembered.model_dump(mode="json")
                    if remembered is not None
                    else None
                ),
            }
            for event_key, (timestamp, remembered) in active.items()
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        _atomic_write_text(self.path, f"{content}\n")

    def _load_active(
        self, now: datetime
    ) -> dict[str, tuple[datetime, ContentItem | None]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        cutoff = now - self.retention
        active: dict[
            str, tuple[datetime, ContentItem | None]
        ] = {}
        for event_key, raw_record in payload.items():
            if isinstance(raw_record, str):
                raw_timestamp = raw_record
                raw_item = None
            else:
                raw_timestamp = raw_record["observed_at"]
                raw_item = raw_record.get("item")
            timestamp = datetime.fromisoformat(raw_timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp >= cutoff:
                remembered = (
                    ContentItem.model_validate(raw_item)
                    if raw_item is not None
                    else None
                )
                active[event_key] = (timestamp, remembered)
        return active
