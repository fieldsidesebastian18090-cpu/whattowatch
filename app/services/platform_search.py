import asyncio
import random
import re
from urllib.parse import quote

import httpx

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


def _normalize(title: str) -> str:
    """Normalize title for fuzzy matching."""
    # Remove common suffixes, punctuation, spaces
    t = re.sub(r'[：:·\-—\s\(\)（）]', '', title)
    return t.lower()


async def _check_platform(
    client: httpx.AsyncClient, platform_key: str, title: str
) -> bool:
    """Check if a movie title is available on a given platform."""
    info = PROVIDERS.get(platform_key)
    if not info:
        return False

    search_url = info["search_url"].format(q=quote(title))

    try:
        resp = await client.get(search_url, headers=_headers(), timeout=12.0)
        resp.raise_for_status()
        html = resp.text

        # Exact title match
        if title in html:
            return True

        # Normalized fuzzy match: strip punctuation and check
        norm_title = _normalize(title)
        norm_html = _normalize(html)
        if len(norm_title) >= 2 and norm_title in norm_html:
            return True

        # Check for "no results" markers
        no_result_markers = ["没有找到", "未找到", "暂无结果", "no results", "No Results", "暂无相关"]
        for marker in no_result_markers:
            if marker in html:
                return False

        return False

    except (httpx.HTTPError, httpx.TimeoutException):
        return False


async def search_platforms(
    title: str, platform_keys: list[str] | None = None
) -> list[dict]:
    """Search multiple platforms for a movie title concurrently."""
    if platform_keys is None:
        platform_keys = list(PROVIDERS.keys())

    matched = []
    async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
        tasks = [_check_platform(client, key, title) for key in platform_keys]
        results = await asyncio.gather(*tasks)

        for key, found in zip(platform_keys, results):
            if found:
                matched.append({
                    "key": key,
                    "name": PROVIDERS[key]["name"],
                })

    return matched
