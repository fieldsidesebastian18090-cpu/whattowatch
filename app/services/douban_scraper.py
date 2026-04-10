import asyncio
import random
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]

DOUBAN_BASE = "https://movie.douban.com/people"
DOUBAN_SUBJECT = "https://movie.douban.com/subject"


@dataclass
class DoubanMovie:
    douban_id: str = ""
    title: str = ""
    year: int | None = None
    user_rating: int | None = None  # 1-5 stars
    status: str = ""  # "watched" or "wish"


@dataclass
class MovieDetail:
    douban_rating: float | None = None
    genres: list[str] | None = None
    directors: list[str] | None = None
    actors: list[str] | None = None
    poster_url: str | None = None


@dataclass
class SyncProgress:
    total_pages: int = 0
    current_page: int = 0
    total_items: int = 0
    enriched_count: int = 0
    enrich_total: int = 0
    phase: str = "idle"  # idle, syncing_watched, syncing_wish, enriching, done, error
    error: str = ""


# In-memory progress tracker keyed by douban_id
_progress: dict[str, SyncProgress] = {}


def get_progress(douban_id: str) -> SyncProgress:
    return _progress.get(douban_id, SyncProgress())


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://movie.douban.com/",
    }


def _parse_list_page(html: str, status: str) -> list[DoubanMovie]:
    """Parse a single page of douban movie list."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".item")
    movies: list[DoubanMovie] = []

    for item in items:
        movie = DoubanMovie(status=status)

        # Extract douban movie ID from link
        link = item.select_one(".title a")
        if link and link.get("href"):
            href = link["href"]
            match = re.search(r"/subject/(\d+)/", href)
            if match:
                movie.douban_id = match.group(1)
            movie.title = link.get_text(strip=True)

        # Extract year from intro line
        intro = item.select_one(".intro")
        if intro:
            text = intro.get_text(strip=True)
            year_match = re.search(r"(\d{4})", text)
            if year_match:
                movie.year = int(year_match.group(1))

        # Extract user rating (stars)
        rating_tag = item.select_one('[class*="rating"]')
        if rating_tag:
            for cls in rating_tag.get("class", []):
                star_match = re.search(r"rating(\d)-t", cls)
                if star_match:
                    movie.user_rating = int(star_match.group(1))
                    break

        if movie.douban_id:
            movies.append(movie)

    return movies


def _get_total_count(html: str) -> int:
    """Extract total item count from the page."""
    soup = BeautifulSoup(html, "html.parser")
    count_tag = soup.select_one("#db-movie-mine h2")
    if count_tag:
        match = re.search(r"(\d+)", count_tag.get_text())
        if match:
            return int(match.group(1))
    paginator = soup.select_one(".paginator .thispage")
    if paginator and paginator.get("data-total-page"):
        return int(paginator["data-total-page"]) * 15
    return 0


def parse_movie_detail(html: str) -> MovieDetail:
    """Parse a Douban movie detail page for metadata."""
    soup = BeautifulSoup(html, "html.parser")
    detail = MovieDetail()

    # Rating
    rating_tag = soup.select_one("strong.rating_num, strong[property='v:average']")
    if rating_tag:
        try:
            detail.douban_rating = float(rating_tag.get_text(strip=True))
        except ValueError:
            pass

    # Genres
    genre_tags = soup.select("span[property='v:genre']")
    if genre_tags:
        detail.genres = [g.get_text(strip=True) for g in genre_tags]

    # Directors
    director_tags = soup.select("a[rel='v:directedBy']")
    if director_tags:
        detail.directors = [d.get_text(strip=True) for d in director_tags]

    # Actors
    actor_tags = soup.select("a[rel='v:starring']")
    if actor_tags:
        detail.actors = [a.get_text(strip=True) for a in actor_tags[:10]]

    # Poster
    poster_tag = soup.select_one("#mainpic img")
    if poster_tag and poster_tag.get("src"):
        detail.poster_url = poster_tag["src"]

    return detail


async def fetch_movie_detail(
    client: httpx.AsyncClient, douban_id: str
) -> MovieDetail | None:
    """Fetch and parse a single movie's detail page."""
    url = f"{DOUBAN_SUBJECT}/{douban_id}/"
    try:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return parse_movie_detail(resp.text)
    except httpx.HTTPError:
        return None


async def scrape_user_movies(
    douban_id: str, status: str, max_pages: int = 20
) -> list[DoubanMovie]:
    """Scrape a user's watched or wish list from Douban."""
    path = "collect" if status == "watched" else "wish"
    url_base = f"{DOUBAN_BASE}/{douban_id}/{path}"
    all_movies: list[DoubanMovie] = []

    progress = _progress.setdefault(douban_id, SyncProgress())
    progress.phase = f"syncing_{status}"
    progress.current_page = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        for page in range(max_pages):
            start = page * 15
            url = f"{url_base}?start={start}&sort=time&rating=all&filter=all&mode=list"

            try:
                resp = await client.get(url, headers=_headers())
                resp.raise_for_status()
            except httpx.HTTPError as e:
                progress.error = f"请求失败: {e}"
                progress.phase = "error"
                break

            html = resp.text

            if page == 0:
                total = _get_total_count(html)
                progress.total_pages = (total + 14) // 15 if total else 1
                progress.total_items += total

            movies = _parse_list_page(html, status)
            if not movies:
                break

            all_movies.extend(movies)
            progress.current_page = page + 1

            await asyncio.sleep(random.uniform(2.0, 4.0))

    return all_movies


async def sync_douban_user(douban_id: str) -> list[DoubanMovie]:
    """Sync both watched and wish lists for a user."""
    _progress[douban_id] = SyncProgress()

    watched = await scrape_user_movies(douban_id, "watched")
    wish = await scrape_user_movies(douban_id, "wish")

    progress = _progress[douban_id]
    if progress.phase != "error":
        progress.phase = "done"

    return watched + wish
