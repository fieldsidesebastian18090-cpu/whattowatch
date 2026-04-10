from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "whattowatch.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Supported streaming platforms with their search URL templates
# {q} will be replaced with the URL-encoded movie title
PROVIDERS = {
    "tencent": {
        "name": "腾讯视频",
        "region": "CN",
        "search_url": "https://v.qq.com/x/search/?q={q}",
        "api_url": "https://pbaccess.video.qq.com/trpc.videosearch.search_cgi.http/load_hotkey_list?search_key={q}",
    },
    "iqiyi": {
        "name": "iQIYI",
        "region": "US",
        "search_url": "https://www.iq.com/search?query={q}",
        "api_url": None,
    },
    "youku": {
        "name": "优酷",
        "region": "CN",
        "search_url": "https://so.youku.com/search_video/q_{q}",
        "api_url": None,
    },
    "mango": {
        "name": "芒果TV",
        "region": "CN",
        "search_url": "https://so.mgtv.com/so?k={q}",
        "api_url": None,
    },
    "netflix": {
        "name": "Netflix",
        "region": "US",
        "search_url": "https://www.netflix.com/search?q={q}",
        "api_url": None,
    },
    "disney": {
        "name": "Disney+",
        "region": "US",
        "search_url": "https://www.disneyplus.com/search/{q}",
        "api_url": None,
    },
    "max": {
        "name": "Max",
        "region": "US",
        "search_url": "https://play.max.com/search?q={q}",
        "api_url": None,
    },
}
