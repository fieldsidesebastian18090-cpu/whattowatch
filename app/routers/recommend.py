from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import PROVIDERS
from ..database import User, get_db
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
    """Get personalized recommendations for user on selected platforms."""
    user = db.query(User).filter(User.douban_id == douban_id).first()
    if not user:
        return {"error": "用户未找到，请先同步豆瓣数据", "items": []}

    platform_keys = [p.strip() for p in platforms.split(",") if p.strip()]

    items = get_recommendations(db, user.id, platform_keys, limit=limit)

    return {
        "douban_id": douban_id,
        "platforms": platform_keys,
        "total": len(items),
        "items": items,
    }
