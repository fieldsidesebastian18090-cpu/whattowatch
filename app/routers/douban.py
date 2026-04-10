import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import Movie, MovieProvider, User, UserMovie, get_db
from ..services import douban_scraper
from ..services.platform_search import search_platforms

router = APIRouter(prefix="/api", tags=["douban"])


class SyncRequest(BaseModel):
    douban_id: str


class SyncResponse(BaseModel):
    message: str
    douban_id: str


async def _do_sync(douban_id: str):
    """Background task: scrape Douban lists + enrich from Douban detail pages + search platforms."""
    from ..database import SessionLocal

    import asyncio
    import random
    import httpx

    # Step 1: Scrape user lists
    all_movies = await douban_scraper.sync_douban_user(douban_id)

    if not all_movies:
        return

    db = SessionLocal()
    try:
        # Ensure user exists
        user = db.query(User).filter(User.douban_id == douban_id).first()
        if not user:
            user = User(douban_id=douban_id)
            db.add(user)
            db.flush()

        # Step 2: Save movies
        for dm in all_movies:
            movie = db.query(Movie).filter(Movie.douban_id == dm.douban_id).first()
            if not movie:
                movie = Movie(
                    douban_id=dm.douban_id,
                    title=dm.title,
                    year=dm.year,
                )
                db.add(movie)
                db.flush()

            um = (
                db.query(UserMovie)
                .filter(UserMovie.user_id == user.id, UserMovie.movie_id == movie.id)
                .first()
            )
            if not um:
                um = UserMovie(
                    user_id=user.id,
                    movie_id=movie.id,
                    status=dm.status,
                    user_rating=dm.user_rating,
                )
                db.add(um)
            else:
                um.status = dm.status
                um.user_rating = dm.user_rating

        db.commit()

        # Step 3: Enrich unenriched movies from Douban detail pages
        movies_to_enrich = (
            db.query(Movie).filter(Movie.enriched == 0).all()
        )

        progress = douban_scraper.get_progress(douban_id)
        progress.phase = "enriching"
        progress.enrich_total = len(movies_to_enrich)
        progress.enriched_count = 0

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            for movie in movies_to_enrich:
                detail = await douban_scraper.fetch_movie_detail(client, movie.douban_id)

                if detail:
                    if detail.douban_rating is not None:
                        movie.douban_rating = detail.douban_rating
                    if detail.genres:
                        movie.genres = json.dumps(detail.genres, ensure_ascii=False)
                    if detail.directors:
                        movie.directors = json.dumps(detail.directors, ensure_ascii=False)
                    if detail.actors:
                        movie.actors = json.dumps(detail.actors, ensure_ascii=False)
                    if detail.poster_url:
                        movie.poster_url = detail.poster_url

                movie.enriched = 1
                progress.enriched_count += 1
                db.commit()

                await asyncio.sleep(random.uniform(2.0, 4.0))

        # Step 4: Search platforms for movies that have no provider data yet
        movies_no_providers = (
            db.query(Movie)
            .outerjoin(MovieProvider)
            .filter(MovieProvider.id.is_(None))
            .all()
        )

        for movie in movies_no_providers:
            matched = await search_platforms(movie.title)
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
            await asyncio.sleep(random.uniform(1.0, 2.0))

        user.last_synced = datetime.utcnow()
        db.commit()

    finally:
        db.close()

    progress = douban_scraper.get_progress(douban_id)
    progress.phase = "done"


@router.post("/sync", response_model=SyncResponse)
async def sync_douban(req: SyncRequest, background_tasks: BackgroundTasks):
    """Start syncing a Douban user's movie data."""
    douban_id = req.douban_id.strip().strip("/").split("/")[-1]
    background_tasks.add_task(_do_sync, douban_id)
    return SyncResponse(message="同步已开始", douban_id=douban_id)


@router.get("/sync/status/{douban_id}")
async def sync_status(douban_id: str):
    """Check the sync progress for a user."""
    progress = douban_scraper.get_progress(douban_id)
    return {
        "phase": progress.phase,
        "current_page": progress.current_page,
        "total_pages": progress.total_pages,
        "total_items": progress.total_items,
        "enriched_count": progress.enriched_count,
        "enrich_total": progress.enrich_total,
        "error": progress.error,
    }


@router.get("/profile/{douban_id}")
async def user_profile(douban_id: str, db: Session = Depends(get_db)):
    """Get user's taste profile summary."""
    from ..services.recommender import build_user_profile

    user = db.query(User).filter(User.douban_id == douban_id).first()
    if not user:
        return {"error": "用户未找到，请先同步豆瓣数据"}

    profile = build_user_profile(db, user.id)

    watched_count = (
        db.query(UserMovie)
        .filter(UserMovie.user_id == user.id, UserMovie.status == "watched")
        .count()
    )
    wish_count = (
        db.query(UserMovie)
        .filter(UserMovie.user_id == user.id, UserMovie.status == "wish")
        .count()
    )

    top_genres = sorted(profile["genre_weights"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_directors = sorted(profile["director_weights"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_actors = sorted(profile["actor_weights"].items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "douban_id": douban_id,
        "last_synced": user.last_synced.isoformat() if user.last_synced else None,
        "watched_count": watched_count,
        "wish_count": wish_count,
        "top_genres": [{"name": g, "weight": round(w, 2)} for g, w in top_genres],
        "top_directors": [{"name": d, "weight": round(w, 2)} for d, w in top_directors],
        "top_actors": [{"name": a, "weight": round(w, 2)} for a, w in top_actors],
    }
