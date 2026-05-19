"""Thin Apify client for the LinkedIn Skills project.

Replaces the previous private HarvestAPI dependency. Each method wraps one
public Apify actor and uses the run-sync-get-dataset-items endpoint, so the
caller gets results back in a single HTTP request (no polling required).

Auth: APIFY_TOKEN env var (or constructor arg).

Actors used (all no-cookies, public, "$1-$5 per 1,000 results"):
  - supreme_coder/linkedin-post
      Fetch post body by URL. Cheapest ($1/1k). Use for hook extraction
      and pre-comment context.
  - apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies
      Fetch comments + replies on a post (by post ID or URL). Use for
      reply-handler thread structure and to avoid duplicate comment takes.
  - apimaestro/linkedin-profile-comments
      Fetch a user's recent comments by username. Use for engagement-monitor
      author-reply tracking.
  - scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies
      Fetch the people who liked or commented on a post. Use for engagement
      analytics (group by seniority, company, role, ICP fit).

Caching: in-process LRU (256 entries, 6h TTL). Pass `force_refresh=True` on
any method to bypass. Retries on transient 408/429/5xx (3 attempts with
exponential backoff + jitter).
"""
from __future__ import annotations
import json
import os
import random
import time
from collections import OrderedDict
from typing import Any, Optional

import requests


class ApifyError(RuntimeError):
    pass


RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 6 * 60 * 60


def _retry(attempts: int = 3, base_delay: float = 0.6):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            last_exc: Optional[Exception] = None
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except ApifyError as e:
                    msg = str(e)
                    retryable = any(f"HTTP {s}" in msg for s in RETRYABLE_STATUSES)
                    if not retryable or attempt == attempts - 1:
                        raise
                    last_exc = e
                except (requests.ConnectionError, requests.Timeout) as e:
                    if attempt == attempts - 1:
                        raise
                    last_exc = e
                time.sleep(base_delay * (2**attempt) + random.uniform(0, 0.25))
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


class ApifyClient:
    BASE_URL = "https://api.apify.com/v2"

    POST_ACTOR = "supreme_coder~linkedin-post"
    POST_COMMENTS_ACTOR = (
        "apimaestro~linkedin-post-comments-replies-engagements-scraper-no-cookies"
    )
    PROFILE_COMMENTS_ACTOR = "apimaestro~linkedin-profile-comments"
    POST_ENGAGERS_ACTOR = (
        "scraping_solutions~linkedin-posts-engagers-likers-and-commenters-no-cookies"
    )

    def __init__(self, token: Optional[str] = None, timeout: float = 180.0):
        self.token = token or os.getenv("APIFY_TOKEN")
        if not self.token:
            raise ApifyError(
                "APIFY_TOKEN not set. Export it or pass token= explicitly."
            )
        self.timeout = timeout
        self._session = requests.Session()
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    # ---- Post body --------------------------------------------------------

    def fetch_post(
        self, post_url: str, *, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Return the post body, author, and engagement stats for one post.

        Args:
            post_url: Any of LinkedIn's three URN URL shapes works.
            force_refresh: If True, bypass cache and re-fetch from Apify.

        Returns:
            Dict with keys: text, authorName, authorProfileUrl, urn, url,
            numLikes, numComments, postedAtISO, plus extra metadata.
        """
        items = self._run_sync(
            self.POST_ACTOR, {"urls": [post_url]}, force_refresh=force_refresh
        )
        if not items:
            raise ApifyError(f"no post returned for {post_url}")
        return items[0]

    # ---- Post comments ----------------------------------------------------

    def fetch_post_comments(
        self,
        *,
        post_id: str,
        max_items: int = 20,
        scrape_replies: bool = False,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return comments (and optionally replies) on a post.

        Args:
            post_id: Activity ID, ugcPost ID, or full post URL.
            max_items: Cap on comments returned.
            scrape_replies: If True, each comment's `replies` list is populated.
            force_refresh: Bypass cache.
        """
        return self._run_sync(
            self.POST_COMMENTS_ACTOR,
            {
                "postIds": [post_id],
                "maxItems": max_items,
                "scrapeReplies": scrape_replies,
            },
            force_refresh=force_refresh,
        )

    # ---- Profile (user) recent comments ----------------------------------

    def fetch_user_recent_comments(
        self,
        *,
        username: str,
        result_limit: int = 30,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return a user's most recent comments across LinkedIn."""
        return self._run_sync(
            self.PROFILE_COMMENTS_ACTOR,
            {"username": username, "resultLimit": result_limit},
            force_refresh=force_refresh,
        )

    # ---- Post engagers (likers + commenters) -----------------------------

    def fetch_post_engagers(
        self,
        *,
        post_url: str,
        max_items: int = 50,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return the people who liked or commented on a post."""
        return self._run_sync(
            self.POST_ENGAGERS_ACTOR,
            {"url": post_url, "maxItems": max_items},
            force_refresh=force_refresh,
        )

    # ---- Cache helpers ----------------------------------------------------

    @staticmethod
    def _cache_key(actor_id: str, payload: dict[str, Any]) -> str:
        return f"{actor_id}::{json.dumps(payload, sort_keys=True, default=str)}"

    def _cache_get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > CACHE_TTL_SECONDS:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    # ---- Internals --------------------------------------------------------

    def _run_sync(
        self,
        actor_id: str,
        payload: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        key = self._cache_key(actor_id, payload)
        if not force_refresh:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        data = self._do_request(actor_id, payload)
        result = data if isinstance(data, list) else []
        self._cache_put(key, result)
        return result

    @_retry()
    def _do_request(
        self, actor_id: str, payload: dict[str, Any]
    ) -> Any:
        url = (
            f"{self.BASE_URL}/acts/{actor_id}/run-sync-get-dataset-items"
            f"?token={self.token}"
        )
        r = self._session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = {"error": r.text[:500]}
            raise ApifyError(f"HTTP {r.status_code}: {body}")
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise ApifyError(f"actor failed: {data['error']}")
        return data
