from fastapi import APIRouter, HTTPException

from modules.ingestion import news_collector

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def get_all_news():
    return news_collector.get_all()


@router.post("/refresh")
def refresh_news():
    new_count = news_collector.collect_all()
    return {"new_articles": new_count, "total": news_collector.total()}


@router.post("/refresh/{norad_id}")
def refresh_news_for_satellite(norad_id: str):
    try:
        new_count = news_collector.collect_for_satellite(norad_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"new_articles": new_count, "total": news_collector.total()}


@router.post("/reset/{norad_id}")
def reset_satellite_news(norad_id: str):
    """Re-fetch articles for a satellite using current KG keywords."""
    try:
        result = news_collector.reset_and_refetch(norad_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{norad_id}")
def get_news_by_satellite(norad_id: str):
    return news_collector.get_by_norad(norad_id)
