import asyncio
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import PROVIDERS
from ..database import Movie, MovieProvider, User, UserMovie, get_db
from ..services.platform_search import search_platforms
from ..services.recommender import get_recommendations

router = APIRouter(prefix="/api", tags=["recommend"])


@router.get("/platforms")
async def list_platforms():
    """List all supported streaming platforms."""
    return [
        {"key": key, "name": info["name"], "region": info["region"]}
        for key, info in PROVIDERS.items()
    ]


@router.get("/recommend/{douban_id}")
async def recommend(
    douban_id: str,
    platforms: str = Query(..., description="逗号分隔的平台key，如 netflix,tencent"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get personalized recommendations: search platforms on-demand, then rank."""
    user = db.query(User).filter(User.douban_id == douban_id).first()
    if not user:
        return {"error": "用户未找到，请先同步豆瓣数据", "items": []}

    platform_keys = [p.strip() for p in platforms.split(",") if p.strip()]

    # Find user's wish list movies that haven't been searched on these platforms yet
    wish_movies = (
        db.query(Movie)
        .join(UserMovie)
        .filter(UserMovie.user_id == user.id, UserMovie.status == "wish")
        .all()
    )

    # Search selected platforms for wish list movies (on-demand)
    stale_cutoff = datetime.utcnow() - timedelta(days=7)
    movies_to_search = []
    for movie in wish_movies:
        # Check if we already have fresh provider data for all selected platforms
        existing_keys = {
            mp.provider_key
            for mp in movie.providers
            if mp.updated_at and mp.updated_at > stale_cutoff
        }
        missing_keys = [k for k in platform_keys if k not in existing_keys]
        if missing_keys:
            movies_to_search.append((movie, missing_keys))

    # Batch search: only search missing platforms for each movie
    for movie, keys_to_search in movies_to_search:
        matched = await search_platforms(movie.title, keys_to_search)
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
        await asyncio.sleep(random.uniform(0.5, 1.0))

    # Now get recommendations with updated provider data
    items = get_recommendations(db, user.id, platform_keys, limit=limit)

    return {
        "douban_id": douban_id,
        "platforms": platform_keys,
        "total": len(items),
        "items": items,
    }
