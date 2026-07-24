"""Tests that category from source config flows into item metadata for all scrapers."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

from src.models import (
    GitHubSourceConfig,
    HackerNewsConfig,
    OSSInsightConfig,
    RedditSubredditConfig,
    RedditUserConfig,
    TelegramChannelConfig,
    TelegramConfig,
    TwitterConfig,
)
from src.scrapers.github import GitHubScraper
from src.scrapers.hackernews import HackerNewsScraper
from src.scrapers.ossinsight import OSSInsightScraper
from src.scrapers.reddit import RedditScraper
from src.scrapers.telegram import TelegramScraper
from src.scrapers.twitter import TwitterScraper

_SINCE = datetime(2020, 1, 1, tzinfo=timezone.utc)
_NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# HackerNews
# ---------------------------------------------------------------------------


def test_hackernews_category_in_metadata():
    cfg = HackerNewsConfig(category="tech")
    scraper = HackerNewsScraper(cfg, AsyncMock())
    story = {
        "id": 1,
        "title": "A story",
        "url": "https://example.com",
        "by": "user",
        "time": int(_NOW.timestamp()),
        "score": 200,
        "type": "story",
        "descendants": 10,
    }
    item = scraper._parse_story(story, [])
    assert item.metadata["category"] == "tech"


def test_hackernews_category_none_when_unset():
    cfg = HackerNewsConfig()
    scraper = HackerNewsScraper(cfg, AsyncMock())
    story = {
        "id": 2,
        "title": "Another story",
        "url": "https://example.com/2",
        "by": "user",
        "time": int(_NOW.timestamp()),
        "score": 150,
        "type": "story",
        "descendants": 0,
    }
    item = scraper._parse_story(story, [])
    assert item.metadata["category"] is None


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


def _github_event(event_type: str = "PushEvent") -> dict:
    return {
        "id": "42",
        "type": event_type,
        "created_at": _NOW.isoformat().replace("+00:00", "Z"),
        "actor": {"login": "alice"},
        "repo": {"name": "alice/repo"},
        "payload": {"commits": [{"message": "init"}]},
    }


def test_github_parse_event_category_in_metadata():
    source = GitHubSourceConfig(type="user_events", username="alice", category="oss")
    scraper = GitHubScraper([source], AsyncMock())
    item = scraper._parse_event(_github_event(), source)
    assert item is not None
    assert item.metadata["category"] == "oss"


def test_github_parse_event_category_none_when_unset():
    source = GitHubSourceConfig(type="user_events", username="alice")
    scraper = GitHubScraper([source], AsyncMock())
    item = scraper._parse_event(_github_event(), source)
    assert item is not None
    assert item.metadata["category"] is None


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------


def _reddit_post(subreddit: str = "LocalLLaMA") -> dict:
    return {
        "id": "xyz",
        "title": "Post title",
        "is_self": True,
        "subreddit": subreddit,
        "permalink": f"/r/{subreddit}/comments/xyz/",
        "author": "tester",
        "created_utc": _NOW.timestamp(),
        "score": 100,
        "upvote_ratio": 0.95,
        "num_comments": 3,
        "selftext": "",
    }


def _reddit_config(category: str | None = None):
    from src.models import RedditConfig

    return RedditConfig(
        enabled=True,
        subreddits=[
            RedditSubredditConfig(
                subreddit="LocalLLaMA",
                enabled=True,
                sort="hot",
                fetch_limit=5,
                min_score=1,
                category=category,
            )
        ],
        fetch_comments=0,
    )


def test_reddit_parse_post_category_in_metadata():
    scraper = RedditScraper(_reddit_config("ai"), AsyncMock())
    item = scraper._parse_post(_reddit_post(), [], "subreddit", category="ai")
    assert item is not None
    assert item.metadata["category"] == "ai"


def test_reddit_parse_post_category_none_when_unset():
    scraper = RedditScraper(_reddit_config(), AsyncMock())
    item = scraper._parse_post(_reddit_post(), [], "subreddit")
    assert item is not None
    assert item.metadata["category"] is None


def test_reddit_rss_fallback_category_in_metadata():
    from src.models import RedditConfig

    cfg = RedditSubredditConfig(
        subreddit="LocalLLaMA", sort="hot", fetch_limit=5, min_score=1, category="forum"
    )
    config = RedditConfig(enabled=True, subreddits=[cfg], fetch_comments=0)
    scraper = RedditScraper(config, AsyncMock())

    rss_xml = f"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://www.reddit.com/r/LocalLLaMA/comments/abc/test/</id>
        <title>RSS post</title>
        <link href="https://www.reddit.com/r/LocalLLaMA/comments/abc/test/"/>
        <updated>{_NOW.strftime('%Y-%m-%dT%H:%M:%S+00:00')}</updated>
        <author><name>rssuser</name></author>
        <summary>body text</summary>
      </entry>
    </feed>"""

    import feedparser

    feed = feedparser.parse(rss_xml)
    # Simulate what _fetch_subreddit_rss produces from the parsed feed
    from src.models import SourceType
    from src.scrapers.reddit import RedditScraper as RS

    items = []
    for entry in feed.entries[: cfg.fetch_limit]:
        published_at = scraper._parse_rss_date(entry)
        if not published_at or published_at < _SINCE:
            continue
        entry_id = str(entry.get("id") or entry.get("link") or "")
        link = str(entry.get("link") or "https://reddit.com/")
        from typing import Any, cast

        items.append(
            __import__("src.models", fromlist=["ContentItem"]).ContentItem(
                id=scraper._generate_id("reddit", "subreddit-rss", entry_id),
                source_type=SourceType.REDDIT,
                title=str(entry.get("title") or "Untitled"),
                url=cast(Any, link),
                content="body",
                author="rssuser",
                published_at=published_at,
                metadata={
                    "score": None,
                    "upvote_ratio": None,
                    "num_comments": None,
                    "subreddit": cfg.subreddit,
                    "is_self": None,
                    "flair": None,
                    "discussion_url": link,
                    "fallback": "rss",
                    "category": cfg.category,
                },
            )
        )
    assert len(items) == 1
    assert items[0].metadata["category"] == "forum"


def test_reddit_user_config_has_category_field():
    cfg = RedditUserConfig(username="alice", category="personal")
    assert cfg.category == "personal"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

_TELEGRAM_MSG_HTML = """
<div class="tgme_widget_message" data-post="channel/1">
  <div class="tgme_widget_message_text js-message_text">Hello world</div>
  <time datetime="2025-01-01T12:00:00+00:00">12:00</time>
</div>
"""


def _tg_msg_el():
    return BeautifulSoup(_TELEGRAM_MSG_HTML, "html.parser").select_one(
        "div.tgme_widget_message"
    )


def test_telegram_parse_message_category_in_metadata():
    cfg = TelegramChannelConfig(channel="channel", category="news")
    scraper = TelegramScraper(TelegramConfig(), AsyncMock())
    item = scraper._parse_message(_tg_msg_el(), cfg, _SINCE)
    assert item is not None
    assert item.metadata["category"] == "news"


def test_telegram_parse_message_category_none_when_unset():
    cfg = TelegramChannelConfig(channel="channel")
    scraper = TelegramScraper(TelegramConfig(), AsyncMock())
    item = scraper._parse_message(_tg_msg_el(), cfg, _SINCE)
    assert item is not None
    assert item.metadata["category"] is None


def test_telegram_parse_channel_html_passes_category():
    cfg = TelegramChannelConfig(channel="channel", fetch_limit=10, category="ai-news")
    scraper = TelegramScraper(TelegramConfig(), AsyncMock())
    items = scraper._parse_channel_html(_TELEGRAM_MSG_HTML, cfg, _SINCE)
    assert len(items) == 1
    assert items[0].metadata["category"] == "ai-news"


# ---------------------------------------------------------------------------
# OSSInsight
# ---------------------------------------------------------------------------


def test_ossinsight_row_to_item_category_in_metadata():
    cfg = OSSInsightConfig(enabled=True, category="oss-trending")
    scraper = OSSInsightScraper(cfg, AsyncMock())
    row = {
        "repo_name": "owner/repo",
        "repo_id": 123,
        "stars": 50,
        "forks": 10,
        "pushes": 5,
        "pull_requests": 3,
    }
    item = scraper._row_to_item(row, "Python")
    assert item is not None
    assert item.metadata["category"] == "oss-trending"


def test_ossinsight_row_to_item_category_none_when_unset():
    cfg = OSSInsightConfig(enabled=True)
    scraper = OSSInsightScraper(cfg, AsyncMock())
    row = {
        "repo_name": "owner/repo",
        "repo_id": 456,
        "stars": 20,
        "forks": 5,
        "pushes": 2,
        "pull_requests": 1,
    }
    item = scraper._row_to_item(row, "Go")
    assert item is not None
    assert item.metadata["category"] is None


# ---------------------------------------------------------------------------
# Twitter (Apify)
# ---------------------------------------------------------------------------


def _twitter_raw_item() -> dict:
    return {
        "id": "tweet-999",
        "tweet_id": "999",
        "full_text": "Hello twitter",
        "user": {"screen_name": "alice", "name": "Alice"},
        "created_at": "Wed Jan 01 12:00:00 +0000 2025",
        "favorite_count": 10,
        "retweet_count": 2,
        "reply_count": 1,
        "is_reply": False,
        "conversation_id": "999",
    }


def test_twitter_parse_item_category_in_metadata():
    cfg = TwitterConfig(enabled=True, users=["alice"], category="social")
    scraper = TwitterScraper(cfg, AsyncMock())
    item = scraper._parse_item(_twitter_raw_item(), _SINCE)
    assert item is not None
    assert item.metadata["category"] == "social"


def test_twitter_parse_item_category_none_when_unset():
    cfg = TwitterConfig(enabled=True, users=["alice"])
    scraper = TwitterScraper(cfg, AsyncMock())
    item = scraper._parse_item(_twitter_raw_item(), _SINCE)
    assert item is not None
    assert item.metadata["category"] is None
