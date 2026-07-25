"""Compliant, metadata-only X API v2 adapter."""

from __future__ import annotations

from datetime import datetime
import os
from urllib.parse import quote

from src.foodscope.config import FoodSourceSpec
from src.models import ContentItem

from .base import BaseFoodAdapter


class XOfficialAPIAdapter(BaseFoodAdapter):
    API_ROOT = "https://api.x.com/2"

    async def fetch(
        self,
        source: FoodSourceSpec,
        since: datetime,
        until: datetime | None = None,
    ) -> list[ContentItem]:
        token_env = source.options.get("bearer_token_env")
        if not isinstance(token_env, str) or not token_env:
            raise ValueError(
                "x_official_api requires bearer_token_env"
            )
        bearer = os.getenv(token_env)
        if not bearer:
            raise ValueError(
                f"missing X bearer token environment variable {token_env}"
            )
        username = source.options.get("username")
        if not isinstance(username, str) or not username:
            raise ValueError("x_official_api requires username")
        headers = {"Authorization": f"Bearer {bearer}"}

        user_response = await self.client.get(
            (
                f"{self.API_ROOT}/users/by/username/"
                f"{quote(username, safe='')}"
            ),
            headers=headers,
        )
        user_response.raise_for_status()
        account_id = str(
            (user_response.json().get("data") or {}).get("id") or ""
        )
        if not account_id:
            raise ValueError(
                f"X API returned no account ID for {username}"
            )

        max_results = max(
            5,
            min(
                int(source.options.get("max_results", 10)),
                100,
            ),
        )
        time_params = {
            "start_time": self.ensure_utc(since)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        if until is not None:
            time_params["end_time"] = (
                self.ensure_utc(until)
                .isoformat()
                .replace("+00:00", "Z")
            )
        posts_response = await self.client.get(
            f"{self.API_ROOT}/users/{quote(account_id, safe='')}/tweets",
            headers=headers,
            params={
                "exclude": "retweets,replies",
                "max_results": max_results,
                "tweet.fields": "created_at",
                **time_params,
            },
        )
        posts_response.raise_for_status()
        records = posts_response.json().get("data") or []
        items: list[ContentItem] = []
        clue_limit = max(
            0,
            min(
                int(source.options.get("max_clue_chars", 280)),
                500,
            ),
        )
        since_utc = self.ensure_utc(since)
        for record in records:
            self.raw_candidate_count += 1
            post_id = str(record.get("id") or "")
            published = self.parse_date(record.get("created_at"))
            self.note_date_result(published)
            if (
                not post_id
                or published is None
                or not self.in_window(
                    published, since_utc, until
                )
            ):
                continue
            clue = " ".join(
                str(record.get("text") or "").split()
            )[:clue_limit]
            post_url = (
                f"https://x.com/{username}/status/{post_id}"
            )
            items.append(
                self.make_item(
                    source,
                    title=f"@{username}: {clue}"[:300],
                    url=post_url,
                    published_at=published,
                    content=clue or None,
                    author=f"@{username}",
                    native_id=post_id,
                    metadata={
                        "x_account_id": account_id,
                        "x_post_id": post_id,
                        "retention_mode": "metadata_only",
                        "evidence_role": "discovery_only",
                        "language": (
                            source.languages[0]
                            if source.languages
                            else None
                        ),
                    },
                )
            )
        return items
