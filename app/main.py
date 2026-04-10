from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import douban, recommend

app = FastAPI(title="WhatToWatch", description="流媒体智能推荐助手")

app.include_router(douban.router)
app.include_router(recommend.router)


@app.get("/api/img")
async def proxy_image(url: str = Query(...)):
    """Proxy Douban images to bypass hotlink protection."""
    if "doubanio.com" not in url and "douban.com" not in url:
        return Response(status_code=403)
    from .services.douban_scraper import get_cookie
    try:
        headers = {
            "Referer": "https://movie.douban.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        cookie = get_cookie()
        if cookie:
            headers["Cookie"] = cookie
        async with httpx.AsyncClient(trust_env=False, timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            content_type = resp.headers.get("content-type", "")
            if content_type.startswith("image"):
                return Response(
                    content=resp.content,
                    media_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400"},
                )
            # Image blocked, return placeholder
            return Response(status_code=404)
    except Exception:
        return Response(status_code=404)


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.on_event("startup")
def startup():
    init_db()
