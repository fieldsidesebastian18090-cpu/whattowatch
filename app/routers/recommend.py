import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import PROVIDERS
from ..database import Movie, User, UserMovie, get_db
from ..services.recommender import build_user_profile

router = APIRouter(prefix="/api", tags=["recommend"])


@router.get("/platforms")
async def list_platforms():
    return [
        {"key": key, "name": info["name"], "region": info["region"]}
        for key, info in PROVIDERS.items()
    ]


def _build_search_links(title: str, platform_keys: list[str]) -> list[dict]:
    links = []
    for key in platform_keys:
        info = PROVIDERS.get(key)
        if info:
            links.append({"key": key, "name": info["name"], "url": info["search_url"].format(q=quote(title))})
    return links


@router.get("/recommend/{douban_id}")
async def recommend(
    douban_id: str,
    platforms: str = Query("", description="逗号分隔的平台key"),
    db: Session = Depends(get_db),
):
    """Return user's wish list items grouped by media type."""
    user = db.query(User).filter(User.douban_id == douban_id).first()
    if not user:
        return {"error": "用户未找到", "movie_wish": [], "tv_wish": [], "book_wish": []}

    platform_keys = [p.strip() for p in platforms.split(",") if p.strip()]
    profile = build_user_profile(db, user.id)

    # Get all wish list items
    wish_items = (
        db.query(Movie)
        .join(UserMovie)
        .filter(UserMovie.user_id == user.id, UserMovie.status == "wish")
        .all()
    )

    movie_wish = []
    tv_wish = []
    book_wish = []

    for movie in wish_items:
        genres = json.loads(movie.genres) if movie.genres else []
        directors = json.loads(movie.directors) if movie.directors else []
        actors = json.loads(movie.actors) if movie.actors else []

        # Preference match score
        genre_w = profile.get("genre_weights", {})
        genre_scores = [genre_w.get(g, 0) for g in genres]
        pref = sum(genre_scores) / max(len(genre_scores), 1) if genre_scores else 0

        item = {
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
            "match_pct": round(min(pref, 1.0) * 100),
            "search_links": _build_search_links(movie.title, platform_keys),
        }

        if movie.media_type == "book":
            book_wish.append(item)
        elif movie.media_type == "tv":
            tv_wish.append(item)
        else:
            movie_wish.append(item)

    # Sort by douban rating desc
    for lst in [movie_wish, tv_wish, book_wish]:
        lst.sort(key=lambda x: x.get("douban_rating") or 0, reverse=True)

    return {
        "douban_id": douban_id,
        "movie_wish": movie_wish,
        "tv_wish": tv_wish,
        "book_wish": book_wish,
    }
