import asyncio
import random
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..config import PROVIDERS

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


async def _check_platform(
    client: httpx.AsyncClient, platform_key: str, title: str
) -> bool:
    """Check if a movie title is available on a given platform by searching its site.

    Returns True if the title appears in search results (best-effort heuristic).
    """
    info = PROVIDERS.get(platform_key)
    if not info:
        return False

    search_url = info["search_url"].format(q=quote(title))

    try:
        resp = await client.get(search_url, headers=_headers(), timeout=15.0)
        resp.raise_for_status()
        html = resp.text

        # Heuristic: if the exact movie title appears in the response body,
        # it's likely available on this platform.
        # We do a case-insensitive check and also look for common result markers.
        if title in html:
            return True

        # Check for common "no results" patterns
        no_result_markers = ["没有找到", "未找到", "暂无结果", "no results", "No Results"]
        for marker in no_result_markers:
            if marker in html:
                return False

        # If page is non-empty and no "no results" marker, be optimistic
        # but require the title to actually appear
        return False

    except (httpx.HTTPError, httpx.TimeoutException):
        return False


async def search_platforms(
    title: str, platform_keys: list[str] | None = None
) -> list[dict]:
    """Search multiple platforms for a movie title.

    Args:
        title: Movie title to search for
        platform_keys: List of platform keys to search. If None, searches all.

    Returns:
        List of matched platforms: [{"key": "netflix", "name": "Netflix"}, ...]
    """
    if platform_keys is None:
        platform_keys = list(PROVIDERS.keys())

    matched = []
    async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
        tasks = []
        for key in platform_keys:
            tasks.append(_check_platform(client, key, title))

        results = await asyncio.gather(*tasks)

        for key, found in zip(platform_keys, results):
            if found:
                matched.append({
                    "key": key,
                    "name": PROVIDERS[key]["name"],
                })

    return matched


async def batch_search_platforms(
    movies: list[dict], platform_keys: list[str] | None = None, concurrency: int = 3
) -> list[list[dict]]:
    """Search platforms for multiple movies with concurrency control.

    Args:
        movies: List of dicts with at least a "title" key.
        platform_keys: Platforms to search.
        concurrency: Max concurrent movie searches.

    Returns:
        List of platform match lists, one per movie.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _search_one(m: dict) -> list[dict]:
        async with sem:
            result = await search_platforms(m["title"], platform_keys)
            await asyncio.sleep(random.uniform(1.0, 2.0))
            return result

    tasks = [_search_one(m) for m in movies]
    return await asyncio.gather(*tasks)
