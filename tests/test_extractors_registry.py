from __future__ import annotations

from src.extractors import ExtractorRegistry, TrafilaturaExtractor
from src.models import TrafilaturaExtractorConfig


def test_default_trafilatura_registered():
    registry = ExtractorRegistry({})
    assert isinstance(registry.get("trafilatura"), TrafilaturaExtractor)


def test_default_trafilatura_uses_default_config():
    registry = ExtractorRegistry({})
    extractor = registry.get("trafilatura")
    assert extractor._config == TrafilaturaExtractorConfig()


def test_unknown_name_returns_none():
    registry = ExtractorRegistry({})
    assert registry.get("nonexistent") is None


def test_user_config_overrides_default():
    registry = ExtractorRegistry({"trafilatura": TrafilaturaExtractorConfig(favor_precision=True)})
    extractor = registry.get("trafilatura")
    assert isinstance(extractor, TrafilaturaExtractor)
    assert extractor._config.favor_precision is True


def test_named_entry_added_alongside_defaults():
    registry = ExtractorRegistry({"my-ext": TrafilaturaExtractorConfig(favor_recall=True)})
    named = registry.get("my-ext")
    assert isinstance(named, TrafilaturaExtractor)
    assert named._config.favor_recall is True
    assert registry.get("trafilatura") is not None
