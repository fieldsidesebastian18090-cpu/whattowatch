import asyncio
import json
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import PROVIDERS
from ..database import Movie, MovieProvider, User, UserMovie, get_db
from ..services.douban_scraper import discover_by_tags
from ..services.platform_search import search_platforms
from ..services.recommender import build_user_profile, get_recommendations

router = APIRouter(prefix="/api", tags=["recommend"])


@router.get("/platforms")
async def list_platforms():
    """List all supported streaming platforms."""
    return [
        {"key": key, "name": info["name"], "region": info["region"]}
        for key, info in PROVIDERS.items()
    ]


async def _search_and_save(db: Session, movie: Movie, platform_keys: list[str]):
    """Search platforms for a movie and save results to DB."""
    stale_cutoff = datetime.utcnow() - timedelta(days=7)
    existing_keys = {
        mp.provider_key
        for mp in movie.providers
        if mp.updated_at and mp.updated_at > stale_cutoff
    }
    missing_keys = [k for k in platform_keys if k not in existing_keys]
    if not missing_keys:
        return

    matched = await search_platforms(movie.title, missing_keys)
    for p in matched:
        existing = (
            db.query(MovieProvider)
            .filter(
                MovieProvider.movie_id == movie.id,
                MovieProvider.provider_key == p["key"],
            )
            .first()
        )
        if not existing:
            db.add(
                MovieProvider(
                    movie_id=movie.id,
                    provider_key=p["key"],
                    provider_name=p["name"],
                    updated_at=datetime.utcnow(),
                )
            )
    db.commit()


@router.get("/recommend/{douban_id}")
async def recommend(
    douban_id: str,
    platforms: str = Query(..., description="逗号分隔的平台key"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get two-section recommendations: wish list + discovery."""
    user = db.query(User).filter(User.douban_id == douban_id).first()
    if not user:
        return {"error": "用户未找到，请先同步豆瓣数据", "wish_items": [], "discover_items": []}

    platform_keys = [p.strip() for p in platforms.split(",") if p.strip()]
    profile = build_user_profile(db, user.id)

    # --- Section 1: Wish list movies ---
    wish_movies = (
        db.query(Movie)
        .join(UserMovie)
        .filter(UserMovie.user_id == user.id, UserMovie.status == "wish")
        .all()
    )

    # Search platforms for wish list movies
    for movie in wish_movies:
        await _search_and_save(db, movie, platform_keys)
        await asyncio.sleep(random.uniform(0.3, 0.6))

    wish_items = get_recommendations(db, user.id, platform_keys, limit=limit)

    # --- Section 2: Discover similar movies ---
    # Get user's top genres
    top_genres = sorted(profile["genre_weights"].items(), key=lambda x: x[1], reverse=True)
    genre_names = [g for g, _ in top_genres[:5]]

    # Get all user's movie douban_ids to exclude
    all_user_movie_ids = {
        m.douban_id
        for m in db.query(Movie)
        .join(UserMovie)
        .filter(UserMovie.user_id == user.id)
        .all()
    }

    # Discover new movies from Douban by user's preferred genres
    discovered = await discover_by_tags(genre_names, all_user_movie_ids, limit=40)

    # Save discovered movies to DB and search platforms
    discover_items = []
    for d in discovered:
        # Upsert movie
        movie = db.query(Movie).filter(Movie.douban_id == d["douban_id"]).first()
        if not movie:
            movie = Movie(
                douban_id=d["douban_id"],
                title=d["title"],
                douban_rating=d.get("douban_rating"),
                poster_url=d.get("poster_url"),
                enriched=0,
            )
            db.add(movie)
            db.flush()

        # Search platforms
        await _search_and_save(db, movie, platform_keys)

        # Check if available on selected platforms
        movie_platforms = [
            {"key": mp.provider_key, "name": mp.provider_name}
            for mp in movie.providers
            if mp.provider_key in platform_keys
        ]

        if not movie_platforms:
            continue

        # Calculate preference score
        douban_score = (movie.douban_rating or 0) / 10.0
        genres = json.loads(movie.genres) if movie.genres else []

        # Simple genre match for discovered movies
        genre_w = profile.get("genre_weights", {})
        genre_scores = [genre_w.get(g, 0) for g in genres] if genres else []
        genre_match = sum(genre_scores) / max(len(genre_scores), 1) if genre_scores else 0.3

        final_score = douban_score * 0.5 + min(genre_match, 1.0) * 0.5
        match_pct = round(min(genre_match, 1.0) * 100)

        discover_items.append({
            "movie_id": movie.id,
            "douban_id": movie.douban_id,
            "title": movie.title,
            "year": movie.year,
            "douban_rating": movie.douban_rating,
            "poster_url": movie.poster_url,
            "genres": genres,
            "directors": json.loads(movie.directors) if movie.directors else [],
            "actors": json.loads(movie.actors) if movie.actors else [],
            "score": round(final_score, 3),
            "match_pct": match_pct,
            "source": "基于偏好推荐",
            "platforms": movie_platforms,
        })

        await asyncio.sleep(random.uniform(0.2, 0.5))

    db.commit()

    discover_items.sort(key=lambda x: x["score"], reverse=True)

    return {
        "douban_id": douban_id,
        "platforms": platform_keys,
        "wish_items": wish_items,
        "discover_items": discover_items[:limit],
    }
