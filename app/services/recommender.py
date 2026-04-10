import json
from collections import Counter

from sqlalchemy.orm import Session

from ..database import Movie, UserMovie


def build_user_profile(db: Session, user_id: int) -> dict:
    """Build a user preference profile from their highly-rated watched movies."""
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


def get_wish_recommendations(db: Session, user_id: int) -> list[Movie]:
    """Get user's wish list movies (not watched)."""
    watched_ids = {
        um.movie_id
        for um in db.query(UserMovie)
        .filter(UserMovie.user_id == user_id, UserMovie.status == "watched")
        .all()
    }

    wish_movies = (
        db.query(Movie)
        .join(UserMovie)
        .filter(UserMovie.user_id == user_id, UserMovie.status == "wish")
        .all()
    )

    return [m for m in wish_movies if m.id not in watched_ids]
