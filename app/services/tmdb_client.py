import asyncio

import httpx

from ..config import PROVIDERS, TMDB_API_KEY, TMDB_BASE_URL

# Rate limiter: simple semaphore to avoid hitting TMDB limits
_semaphore = asyncio.Semaphore(8)


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    """Make a rate-limited GET request to TMDB API."""
    async with _semaphore:
        url = f"{TMDB_BASE_URL}{path}"
        default_params = {"api_key": TMDB_API_KEY, "language": "zh-CN"}
        if params:
            default_params.update(params)
        resp = await client.get(url, params=default_params, timeout=15.0)
        resp.raise_for_status()
        await asyncio.sleep(0.05)  # ~20 req/s max
        return resp.json()


async def search_movie(client: httpx.AsyncClient, title: str, year: int | None = None) -> dict | None:
    """Search TMDB for a movie by title and optional year. Returns first match or None."""
    params = {"query": title}
    if year:
        params["year"] = str(year)

    data = await _get(client, "/search/movie", params)
    results = data.get("results", [])

    if not results and year:
        # Retry without year if no match
        data = await _get(client, "/search/movie", {"query": title})
        results = data.get("results", [])

    return results[0] if results else None


async def get_movie_details(client: httpx.AsyncClient, tmdb_id: int) -> dict:
    """Get movie details including genres, credits."""
    data = await _get(client, f"/movie/{tmdb_id}", {"append_to_response": "credits"})
    return data


async def get_watch_providers(client: httpx.AsyncClient, tmdb_id: int) -> dict[str, list[dict]]:
    """Get streaming providers for a movie.

    Returns dict keyed by region code (CN, US) with lists of provider info.
    """
    data = await _get(client, f"/movie/{tmdb_id}/watch/providers")
    results = data.get("results", {})

    providers: dict[str, list[dict]] = {}
    for region in ("CN", "US"):
        region_data = results.get(region, {})
        flatrate = region_data.get("flatrate", [])
        providers[region] = flatrate

    return providers


def match_providers(provider_data: dict[str, list[dict]]) -> list[dict]:
    """Match TMDB provider data against our supported platforms.

    Returns list of matched platforms: [{key, name, provider_id}]
    """
    matched = []
    for key, info in PROVIDERS.items():
        region = info["region"]
        region_providers = provider_data.get(region, [])
        for p in region_providers:
            if p.get("provider_id") == info["id"]:
                matched.append({
                    "key": key,
                    "name": info["name"],
                    "provider_id": info["id"],
                })
                break
    return matched


async def enrich_movie(title: str, year: int | None = None) -> dict | None:
    """Search and enrich a movie with TMDB data + provider info.

    Returns dict with tmdb_id, genres, directors, actors, poster_url, providers
    or None if not found.
    """
    if not TMDB_API_KEY:
        return None

    async with httpx.AsyncClient() as client:
        result = await search_movie(client, title, year)
        if not result:
            return None

        tmdb_id = result["id"]
        details = await get_movie_details(client, tmdb_id)
        provider_data = await get_watch_providers(client, tmdb_id)

        genres = [g["name"] for g in details.get("genres", [])]
        credits = details.get("credits", {})
        directors = [
            c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"
        ]
        actors = [c["name"] for c in credits.get("cast", [])[:10]]

        poster_path = details.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w300{poster_path}" if poster_path else None

        return {
            "tmdb_id": tmdb_id,
            "genres": genres,
            "directors": directors,
            "actors": actors,
            "poster_url": poster_url,
            "douban_rating": details.get("vote_average"),
            "providers": match_providers(provider_data),
        }


async def batch_enrich(movies: list[dict], concurrency: int = 5) -> list[dict]:
    """Enrich multiple movies concurrently.

    Each item in movies should have 'title' and optionally 'year'.
    Returns list of enrichment results (or None for unfound).
    """
    if not TMDB_API_KEY:
        return [None] * len(movies)

    sem = asyncio.Semaphore(concurrency)

    async def _enrich_one(m: dict) -> dict | None:
        async with sem:
            result = await enrich_movie(m["title"], m.get("year"))
            await asyncio.sleep(0.3)  # Extra spacing for batch
            return result

    tasks = [_enrich_one(m) for m in movies]
    return await asyncio.gather(*tasks)
