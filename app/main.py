from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import douban, recommend

app = FastAPI(title="WhatToWatch", description="流媒体智能推荐助手")

app.include_router(douban.router)
app.include_router(recommend.router)

static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.on_event("startup")
def startup():
    init_db()
