from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    douban_id = Column(Text, unique=True, nullable=False)
    last_synced = Column(DateTime, nullable=True)

    movies = relationship("UserMovie", back_populates="user")


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    douban_id = Column(Text, unique=True, nullable=False)
    title = Column(Text, nullable=False)
    enriched = Column(Integer, default=0)  # 0=pending, 1=done
    year = Column(Integer, nullable=True)
    douban_rating = Column(Float, nullable=True)
    genres = Column(Text, default="[]")  # JSON array
    directors = Column(Text, default="[]")  # JSON array
    actors = Column(Text, default="[]")  # JSON array
    poster_url = Column(Text, nullable=True)

    user_movies = relationship("UserMovie", back_populates="movie")
    providers = relationship("MovieProvider", back_populates="movie")


class UserMovie(Base):
    __tablename__ = "user_movies"
    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_user_movie"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    status = Column(Text, nullable=False)  # "watched" or "wish"
    user_rating = Column(Integer, nullable=True)  # 1-5 stars

    user = relationship("User", back_populates="movies")
    movie = relationship("Movie", back_populates="user_movies")


class MovieProvider(Base):
    __tablename__ = "movie_providers"
    __table_args__ = (
        UniqueConstraint("movie_id", "provider_key", name="uq_movie_provider"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    provider_key = Column(Text, nullable=False)  # e.g. "netflix", "tencent"
    provider_name = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

    movie = relationship("Movie", back_populates="providers")


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
