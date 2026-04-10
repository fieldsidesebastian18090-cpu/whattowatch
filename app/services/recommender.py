import json
from collections import Counter

from sqlalchemy.orm import Session

from ..database import Movie, MovieProvider, UserMovie


def build_user_profile(db: Session, user_id: int) -> dict:
    """Build a user preference profile from their highly-rated watched movies.

    Returns:
        {
            "genre_weights": {"科幻": 0.3, "剧情": 0.5, ...},
            "director_weights": {"Christopher Nolan": 0.2, ...},
            "actor_weights": {"Leonardo DiCaprio": 0.15, ...},
            "total_rated": 5
        }
    """
    # Get movies the user rated 4+ stars
    high_rated = (
        db.query(UserMovie)
        .filter(
            UserMovie.user_id == user_id,
            UserMovie.status == "watched",
            UserMovie.user_rating >= 4,
        )
        .all()
    )

    if not high_rated:
        # Fallback: use all watched movies
        high_rated = (
            db.query(UserMovie)
            .filter(UserMovie.user_id == user_id, UserMovie.status == "watched")
            .all()
        )

    genre_counter: Counter = Counter()
    director_counter: Counter = Counter()
    actor_counter: Counter = Counter()

    for um in high_rated:
        movie = um.movie
        if not movie:
            continue

        genres = json.loads(movie.genres) if movie.genres else []
        directors = json.loads(movie.directors) if movie.directors else []
        actors = json.loads(movie.actors) if movie.actors else []

        for g in genres:
            genre_counter[g] += 1
        for d in directors:
            director_counter[d] += 1
        for a in actors:
            actor_counter[a] += 1

    total = len(high_rated) or 1

    return {
        "genre_weights": {k: v / total for k, v in genre_counter.items()},
        "director_weights": {k: v / total for k, v in director_counter.items()},
        "actor_weights": {k: v / total for k, v in actor_counter.items()},
        "total_rated": len(high_rated),
    }


def _preference_score(movie: Movie, profile: dict) -> float:
    """Calculate how well a movie matches the user's taste (0-1)."""
    genre_w = profile.get("genre_weights", {})
    director_w = profile.get("director_weights", {})
    actor_w = profile.get("actor_weights", {})

    genres = json.loads(movie.genres) if movie.genres else []
    directors = json.loads(movie.directors) if movie.directors else []
    actors = json.loads(movie.actors) if movie.actors else []

    # Genre match: average of matching genre weights
    genre_scores = [genre_w.get(g, 0) for g in genres]
    genre_match = sum(genre_scores) / max(len(genre_scores), 1)

    # Director match: max match
    director_scores = [director_w.get(d, 0) for d in directors]
    director_match = max(director_scores) if director_scores else 0

    # Actor match: average of top-3 actor matches
    actor_scores = sorted([actor_w.get(a, 0) for a in actors], reverse=True)[:3]
    actor_match = sum(actor_scores) / max(len(actor_scores), 1)

    # Normalize each component to 0-1 range (cap at 1)
    genre_match = min(genre_match, 1.0)
    director_match = min(director_match, 1.0)
    actor_match = min(actor_match, 1.0)

    return genre_match * 0.6 + director_match * 0.25 + actor_match * 0.15


def get_recommendations(
    db: Session,
    user_id: int,
    platform_keys: list[str],
    limit: int = 30,
) -> list[dict]:
    """Get personalized movie recommendations filtered by selected platforms.

    Returns list of dicts:
        [{movie, score, match_pct, source, platforms}]
    """
    from ..config import PROVIDERS

    profile = build_user_profile(db, user_id)

    # Get user's wish list movie IDs
    wish_movie_ids = {
        um.movie_id
        for um in db.query(UserMovie)
        .filter(UserMovie.user_id == user_id, UserMovie.status == "wish")
        .all()
    }

    # Get user's watched movie IDs (to exclude)
    watched_movie_ids = {
        um.movie_id
        for um in db.query(UserMovie)
        .filter(UserMovie.user_id == user_id, UserMovie.status == "watched")
        .all()
    }

    # Get provider IDs for selected platforms
    selected_provider_ids = {
        PROVIDERS[k]["id"] for k in platform_keys if k in PROVIDERS
    }

    # Find all movies available on selected platforms
    available_movies = (
        db.query(Movie)
        .join(MovieProvider)
        .filter(MovieProvider.provider_id.in_(selected_provider_ids))
        .all()
    )

    results = []
    for movie in available_movies:
        if movie.id in watched_movie_ids:
            continue

        # Douban score normalized to 0-1
        douban_score = (movie.douban_rating or 0) / 10.0

        # Preference match
        pref_score = _preference_score(movie, profile)

        # Final score
        final_score = douban_score * 0.5 + pref_score * 0.5

        # Determine source label
        is_wish = movie.id in wish_movie_ids
        source = "来自想看清单" if is_wish else "基于偏好推荐"

        # Boost wish list items slightly
        if is_wish:
            final_score = min(final_score + 0.05, 1.0)

        # Get platforms this movie is on (among selected)
        movie_platforms = [
            {"key": mp.provider_id, "name": mp.provider_name}
            for mp in movie.providers
            if mp.provider_id in selected_provider_ids
        ]

        results.append({
            "movie_id": movie.id,
            "douban_id": movie.douban_id,
            "title": movie.title,
            "year": movie.year,
            "douban_rating": movie.douban_rating,
            "poster_url": movie.poster_url,
            "genres": json.loads(movie.genres) if movie.genres else [],
            "score": round(final_score, 3),
            "match_pct": round(pref_score * 100),
            "source": source,
            "platforms": movie_platforms,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
