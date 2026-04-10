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
    media_type: str = "movie"  # "movie", "tv", "book"


@dataclass
class MovieDetail:
    douban_rating: float | None = None
    genres: list[str] | None = None
    directors: list[str] | None = None
    actors: list[str] | None = None
    poster_url: str | None = None
    media_type: str | None = None  # detected from detail page


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

# Douban cookie for authenticated requests
_douban_cookie: str = ""


def set_cookie(cookie: str):
    global _douban_cookie
    _douban_cookie = cookie


def get_cookie() -> str:
    return _douban_cookie


def get_progress(douban_id: str) -> SyncProgress:
    return _progress.get(douban_id, SyncProgress())


def _headers() -> dict[str, str]:
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://movie.douban.com/",
    }
    if _douban_cookie:
        h["Cookie"] = _douban_cookie
    return h


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

    # Try multiple selectors for the count
    for selector in ["#db-movie-mine h2", ".article h2", "#content h2"]:
        tag = soup.select_one(selector)
        if tag:
            match = re.search(r"(\d+)", tag.get_text())
            if match:
                return int(match.group(1))

    # Try paginator: last page number * items per page
    last_page = soup.select_one(".paginator .thispage")
    if last_page and last_page.get("data-total-page"):
        return int(last_page["data-total-page"]) * 15

    # Fallback: count items on current page
    items = soup.select(".item")
    return len(items)


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

    # Detect TV show vs movie
    info_text = soup.select_one("#info")
    info_str = info_text.get_text() if info_text else ""
    if "集数" in info_str or "首播" in info_str:
        detail.media_type = "tv"
    else:
        detail.media_type = "movie"

    return detail


async def _solve_douban_challenge(
    client: httpx.AsyncClient, html: str, resp_url: str
) -> str | None:
    """Solve Douban's SHA-512 proof-of-work anti-bot challenge.

    Returns the real page HTML, or None if solving fails.
    """
    import hashlib

    soup = BeautifulSoup(html, "html.parser")
    tok_tag = soup.select_one("#tok")
    cha_tag = soup.select_one("#cha")
    red_tag = soup.select_one("#red")

    if not tok_tag or not cha_tag:
        return None

    tok = tok_tag.get("value", "")
    cha = cha_tag.get("value", "")
    redirect_url = red_tag.get("value", "") if red_tag else ""

    # Find nonce where sha512(cha + nonce) starts with "0000"
    nonce = 0
    while True:
        nonce += 1
        h = hashlib.sha512((cha + str(nonce)).encode()).hexdigest()
        if h[:4] == "0000":
            break
        if nonce > 5_000_000:
            return None

    # Extract form action base URL
    form = soup.select_one("#sec")
    action = form.get("action", "/c") if form else "/c"

    # Build the POST URL from sec.douban.com
    from urllib.parse import urljoin
    post_url = urljoin(str(resp_url), action)

    post_resp = await client.post(
        post_url,
        data={"tok": tok, "cha": cha, "sol": str(nonce)},
        headers=_headers(),
    )

    # Should redirect to the real page
    if post_resp.status_code in (200,) and len(post_resp.text) > 5000:
        return post_resp.text

    return None


async def fetch_movie_detail(
    client: httpx.AsyncClient, douban_id: str
) -> MovieDetail | None:
    """Fetch and parse a single movie's detail page, solving anti-bot challenges."""
    url = f"{DOUBAN_SUBJECT}/{douban_id}/"
    try:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        html = resp.text

        # Check if we hit the anti-bot challenge page
        if "sec.douban.com" in str(resp.url) or 'id="sec"' in html:
            html = await _solve_douban_challenge(client, html, str(resp.url))
            if not html:
                return None

        return parse_movie_detail(html)
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

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, trust_env=False) as client:
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


async def discover_by_tags(
    tags: list[str], exclude_ids: set[str],
    media_type: str = "movie", limit: int = 50
) -> list[dict]:
    """Discover movies/TV from Douban by genre tags (JSON API).

    Args:
        media_type: "movie" or "tv"
    """
    discovered = {}
    douban_type = "tv" if media_type == "tv" else "movie"

    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, trust_env=False) as client:
        for tag in tags[:5]:
            try:
                resp = await client.get(
                    "https://movie.douban.com/j/search_subjects",
                    params={
                        "type": douban_type,
                        "tag": tag,
                        "sort": "recommend",
                        "page_limit": 20,
                        "page_start": 0,
                    },
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("subjects", []):
                    did = item.get("id", "")
                    if did and did not in exclude_ids and did not in discovered:
                        rate = item.get("rate", "")
                        discovered[did] = {
                            "douban_id": did,
                            "title": item.get("title", ""),
                            "douban_rating": float(rate) if rate else None,
                            "poster_url": item.get("cover", ""),
                            "media_type": media_type,
                        }
            except (httpx.HTTPError, ValueError):
                continue

            await asyncio.sleep(random.uniform(0.5, 1.0))
            if len(discovered) >= limit:
                break

    return list(discovered.values())[:limit]


# ========== Book Scraping ==========

BOOK_BASE = "https://book.douban.com/people"
BOOK_SUBJECT = "https://book.douban.com/subject"


def _parse_book_list_page(html: str, status: str) -> list[DoubanMovie]:
    """Parse a Douban book list page (mode=list)."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.item")
    books: list[DoubanMovie] = []

    for item in items:
        book = DoubanMovie(status=status, media_type="book")

        # Title and ID from .title a
        link = item.select_one(".title a")
        if link and link.get("href"):
            href = link["href"]
            match = re.search(r"/subject/(\d+)/", href)
            if match:
                book.douban_id = match.group(1)
            book.title = link.get_text(strip=True)

        # Year from .intro text
        intro = item.select_one(".intro")
        if intro:
            text = intro.get_text(strip=True)
            year_match = re.search(r"(\d{4})", text)
            if year_match:
                book.year = int(year_match.group(1))

        # User rating from .date span
        date_div = item.select_one(".date")
        if date_div:
            rating_tag = date_div.select_one('[class*="rating"]')
            if rating_tag:
                for cls in rating_tag.get("class", []):
                    star_match = re.search(r"rating(\d)-t", cls)
                    if star_match:
                        book.user_rating = int(star_match.group(1))
                        break

        if book.douban_id:
            books.append(book)

    return books


def _get_book_total_count(html: str) -> int:
    """Extract total count from book list page."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in ["#db-book-mine h2", ".article h2", "h2"]:
        tag = soup.select_one(selector)
        if tag:
            match = re.search(r"(\d+)", tag.get_text())
            if match:
                return int(match.group(1))
    items = soup.select("li.item")
    return len(items)


def parse_book_detail(html: str) -> MovieDetail:
    """Parse a Douban book detail page."""
    soup = BeautifulSoup(html, "html.parser")
    detail = MovieDetail(media_type="book")

    # Rating
    rating_tag = soup.select_one("strong.rating_num, strong[property='v:average']")
    if rating_tag:
        try:
            detail.douban_rating = float(rating_tag.get_text(strip=True))
        except ValueError:
            pass

    # Author (stored in directors field)
    info = soup.select_one("#info")
    if info:
        info_text = info.get_text()
        author_match = re.search(r"作者[:\s]*(.+?)(?:\n|出版)", info_text)
        if author_match:
            authors = [a.strip() for a in re.split(r'[/,，]', author_match.group(1)) if a.strip()]
            detail.directors = authors[:5]

    # Genres/tags
    tag_tags = soup.select("a.tag")
    if tag_tags:
        detail.genres = [t.get_text(strip=True) for t in tag_tags[:10]]

    # Cover
    poster_tag = soup.select_one("#mainpic img")
    if poster_tag and poster_tag.get("src"):
        detail.poster_url = poster_tag["src"]

    return detail


async def fetch_book_detail(
    client: httpx.AsyncClient, douban_id: str
) -> MovieDetail | None:
    """Fetch and parse a book detail page."""
    url = f"{BOOK_SUBJECT}/{douban_id}/"
    try:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        html = resp.text

        if "sec.douban.com" in str(resp.url) or 'id="sec"' in html:
            html = await _solve_douban_challenge(client, html, str(resp.url))
            if not html:
                return None

        return parse_book_detail(html)
    except httpx.HTTPError:
        return None


async def scrape_user_books(
    douban_id: str, status: str, max_pages: int = 20
) -> list[DoubanMovie]:
    """Scrape a user's read or wish-to-read book list."""
    path = "collect" if status == "watched" else "wish"
    url_base = f"{BOOK_BASE}/{douban_id}/{path}"
    all_books: list[DoubanMovie] = []

    progress = _progress.setdefault(douban_id, SyncProgress())
    progress.phase = f"syncing_books_{status}"
    progress.current_page = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, trust_env=False) as client:
        for page in range(max_pages):
            start = page * 15
            url = f"{url_base}?start={start}&sort=time&rating=all&filter=all&mode=list"

            try:
                resp = await client.get(url, headers=_headers())
                resp.raise_for_status()
            except httpx.HTTPError as e:
                progress.error = f"书籍请求失败: {e}"
                break

            html = resp.text

            if page == 0:
                total = _get_book_total_count(html)
                progress.total_pages = (total + 14) // 15 if total else 1
                progress.total_items += total

            books = _parse_book_list_page(html, status)
            if not books:
                break

            all_books.extend(books)
            progress.current_page = page + 1

            await asyncio.sleep(random.uniform(2.0, 4.0))

    return all_books


async def sync_douban_user_full(douban_id: str) -> list[DoubanMovie]:
    """Sync movies, TV shows, and books for a user."""
    _progress[douban_id] = SyncProgress()

    # Movies + TV (from movie.douban.com, distinguished during enrichment)
    watched = await scrape_user_movies(douban_id, "watched")
    wish = await scrape_user_movies(douban_id, "wish")

    # Books (from book.douban.com)
    books_read = await scrape_user_books(douban_id, "watched")
    books_wish = await scrape_user_books(douban_id, "wish")

    progress = _progress[douban_id]
    if progress.phase != "error":
        progress.phase = "done"

    return watched + wish + books_read + books_wish


async def discover_books_by_tags(
    tags: list[str], exclude_ids: set[str], limit: int = 30
) -> list[dict]:
    """Discover books from Douban by searching tags."""
    discovered = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, trust_env=False) as client:
        for tag in tags[:5]:
            try:
                url = f"https://book.douban.com/tag/{tag}"
                resp = await client.get(url, headers=_headers())
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                for item in soup.select(".subject-item"):
                    link = item.select_one("h2 a")
                    if not link or not link.get("href"):
                        continue
                    match = re.search(r"/subject/(\d+)/", link["href"])
                    if not match:
                        continue
                    did = match.group(1)
                    if did in exclude_ids or did in discovered:
                        continue

                    title = link.get_text(strip=True)
                    rating_tag = item.select_one(".rating_nums")
                    rating = None
                    if rating_tag:
                        try:
                            rating = float(rating_tag.get_text(strip=True))
                        except ValueError:
                            pass

                    cover_tag = item.select_one("img")
                    cover = cover_tag.get("src", "") if cover_tag else ""

                    discovered[did] = {
                        "douban_id": did,
                        "title": title,
                        "douban_rating": rating,
                        "poster_url": cover,
                        "media_type": "book",
                    }
            except (httpx.HTTPError, ValueError):
                continue

            await asyncio.sleep(random.uniform(0.5, 1.0))
            if len(discovered) >= limit:
                break

    return list(discovered.values())[:limit]
