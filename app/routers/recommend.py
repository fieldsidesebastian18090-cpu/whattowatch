import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import PROVIDERS
from ..database import Movie, User, UserMovie, get_db
from ..services.douban_scraper import discover_books_by_tags, discover_by_tags
from ..services.recommender import build_user_profile, get_wish_recommendations

router = APIRouter(prefix="/api", tags=["recommend"])


@router.get("/platforms")
async def list_platforms():
    """List all supported streaming platforms."""
    return [
        {"key": key, "name": info["name"], "region": info["region"]}
        for key, info in PROVIDERS.items()
    ]


def _build_search_links(title: str, platform_keys: list[str]) -> list[dict]:
    """Build search URLs for selected platforms."""
    links = []
    for key in platform_keys:
        info = PROVIDERS.get(key)
        if info:
            links.append({
                "key": key,
                "name": info["name"],
                "url": info["search_url"].format(q=quote(title)),
            })
    return links


def _score_item(movie: Movie, profile: dict, is_wish: bool) -> dict:
    """Score and format a movie/TV item for the response."""
    genres = json.loads(movie.genres) if movie.genres else []
    directors = json.loads(movie.directors) if movie.directors else []
    actors = json.loads(movie.actors) if movie.actors else []

    douban_score = (movie.douban_rating or 0) / 10.0

    genre_w = profile.get("genre_weights", {})
    genre_scores = [genre_w.get(g, 0) for g in genres]
    genre_match = sum(genre_scores) / max(len(genre_scores), 1) if genre_scores else 0

    director_w = profile.get("director_weights", {})
    director_scores = [director_w.get(d, 0) for d in directors]
    director_match = max(director_scores) if director_scores else 0

    actor_w = profile.get("actor_weights", {})
    actor_scores = sorted([actor_w.get(a, 0) for a in actors], reverse=True)[:3]
    actor_match = sum(actor_scores) / max(len(actor_scores), 1) if actor_scores else 0

    pref_score = min(genre_match, 1.0) * 0.6 + min(director_match, 1.0) * 0.25 + min(actor_match, 1.0) * 0.15
    final_score = douban_score * 0.5 + pref_score * 0.5
    if is_wish:
        final_score = min(final_score + 0.05, 1.0)

    return {
        "movie_id": movie.id,
        "douban_id": movie.douban_id,
        "media_type": movie.media_type or "movie",
        "title": movie.title,
        "year": movie.year,
        "douban_rating": movie.douban_rating,
        "poster_url": movie.poster_url,
        "genres": genres,
        "directors": directors,
        "actors": actors,
        "score": round(final_score, 3),
        "match_pct": round(pref_score * 100),
    }


@router.get("/recommend/{douban_id}")
async def recommend(
    douban_id: str,
    platforms: str = Query("", description="逗号分隔的平台key"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Instant recommendations: wish list + discovery for movies/TV/books."""
    user = db.query(User).filter(User.douban_id == douban_id).first()
    if not user:
        return {"error": "用户未找到", "wish_items": [], "discover_items": [], "book_items": []}

    platform_keys = [p.strip() for p in platforms.split(",") if p.strip()]
    profile = build_user_profile(db, user.id)

    # --- Wish list items (movies + TV) ---
    wish_movies = (
        db.query(Movie)
        .join(UserMovie)
        .filter(
            UserMovie.user_id == user.id,
            UserMovie.status == "wish",
            Movie.media_type.in_(["movie", "tv"]),
        )
        .all()
    )

    watched_ids = {
        um.movie_id
        for um in db.query(UserMovie)
        .filter(UserMovie.user_id == user.id, UserMovie.status == "watched")
        .all()
    }

    wish_items = []
    for movie in wish_movies:
        if movie.id in watched_ids:
            continue
        item = _score_item(movie, profile, is_wish=True)
        item["source"] = "来自想看清单"
        item["search_links"] = _build_search_links(movie.title, platform_keys)
        wish_items.append(item)
    wish_items.sort(key=lambda x: x["score"], reverse=True)

    # --- Discover movies + TV ---
    top_genres = sorted(profile["genre_weights"].items(), key=lambda x: x[1], reverse=True)
    genre_names = [g for g, _ in top_genres[:5]]

    all_user_douban_ids = {
        m.douban_id
        for m in db.query(Movie).join(UserMovie).filter(UserMovie.user_id == user.id).all()
    }

    # Discover movies and TV shows
    discovered_movies = await discover_by_tags(genre_names, all_user_douban_ids, "movie", limit=5)
    discovered_tv = await discover_by_tags(genre_names, all_user_douban_ids, "tv", limit=5)

    discover_items = []
    for d in discovered_movies + discovered_tv:
        movie = db.query(Movie).filter(Movie.douban_id == d["douban_id"]).first()
        if not movie:
            movie = Movie(
                douban_id=d["douban_id"],
                title=d["title"],
                douban_rating=d.get("douban_rating"),
                poster_url=d.get("poster_url"),
                media_type=d.get("media_type", "movie"),
                enriched=0,
            )
            db.add(movie)
            db.flush()

        item = _score_item(movie, profile, is_wish=False)
        item["source"] = "基于偏好推荐"
        item["search_links"] = _build_search_links(movie.title, platform_keys)
        discover_items.append(item)

    db.commit()
    discover_items.sort(key=lambda x: x["score"], reverse=True)

    # --- Wish list books ---
    wish_books = (
        db.query(Movie)
        .join(UserMovie)
        .filter(
            UserMovie.user_id == user.id,
            UserMovie.status == "wish",
            Movie.media_type == "book",
        )
        .all()
    )

    book_items = []
    for book in wish_books:
        item = {
            "movie_id": book.id,
            "douban_id": book.douban_id,
            "media_type": "book",
            "title": book.title,
            "year": book.year,
            "douban_rating": book.douban_rating,
            "poster_url": book.poster_url,
            "genres": json.loads(book.genres) if book.genres else [],
            "directors": json.loads(book.directors) if book.directors else [],  # authors
            "actors": [],
            "source": "来自想读清单",
        }
        book_items.append(item)

    # Also discover books
    book_genres = [g for g, _ in top_genres[:3]]
    discovered_books = await discover_books_by_tags(book_genres, all_user_douban_ids, limit=5)

    for d in discovered_books:
        book = db.query(Movie).filter(Movie.douban_id == d["douban_id"]).first()
        if not book:
            book = Movie(
                douban_id=d["douban_id"],
                title=d["title"],
                douban_rating=d.get("douban_rating"),
                poster_url=d.get("poster_url"),
                media_type="book",
                enriched=0,
            )
            db.add(book)
            db.flush()

        book_items.append({
            "movie_id": book.id,
            "douban_id": book.douban_id,
            "media_type": "book",
            "title": book.title,
            "year": book.year,
            "douban_rating": book.douban_rating,
            "poster_url": book.poster_url,
            "genres": json.loads(book.genres) if book.genres else [],
            "directors": json.loads(book.directors) if book.directors else [],
            "actors": [],
            "source": "基于偏好推荐",
        })

    db.commit()

    return {
        "douban_id": douban_id,
        "platforms": platform_keys,
        "wish_items": wish_items[:limit],
        "discover_items": discover_items[:limit],
        "book_items": book_items[:limit],
    }
