import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "whattowatch.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# TMDB provider IDs for each platform
PROVIDERS = {
    "tencent": {"id": 613, "name": "腾讯视频", "region": "CN"},
    "iqiyi": {"id": 617, "name": "爱奇艺", "region": "CN"},
    "youku": {"id": 614, "name": "优酷", "region": "CN"},
    "mango": {"id": 618, "name": "芒果TV", "region": "CN"},
    "netflix": {"id": 8, "name": "Netflix", "region": "US"},
    "disney": {"id": 337, "name": "Disney+", "region": "US"},
    "max": {"id": 1899, "name": "Max", "region": "US"},
}
