"""
Config Routes — System configuration and monitoring endpoints.
POST /api/config         → Push config from Jenkins plugin
GET  /api/tokens         → Get token usage today
GET  /api/incidents      → Get incident summaries from Chroma metadata
GET  /api/incidents/{id} → Get single incident detail
"""

from fastapi import APIRouter
from config import AI_PROVIDER, TOKEN_DAILY_LIMIT, CONFIDENCE_THRESHOLD, MAX_LOOPS
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Configuration"])


@router.get("/tokens")
async def get_token_usage():
    """Get current daily token usage and remaining budget."""
    # TODO: Day 2 — wire to actual TokenBudget instance
    return {
        "daily_limit": TOKEN_DAILY_LIMIT,
        "used_today": 0,
        "remaining": TOKEN_DAILY_LIMIT,
        "ai_provider": AI_PROVIDER,
    }


@router.get("/config")
async def get_config():
    """Get current engine configuration (non-sensitive)."""
    return {
        "ai_provider": AI_PROVIDER,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "max_loops": MAX_LOOPS,
        "token_daily_limit": TOKEN_DAILY_LIMIT,
    }


@router.get("/incidents")
async def get_incidents():
    """Get recent incident summaries from Chroma metadata."""
    # TODO: Day 5 — query Chroma metadata for incident history
    return {"incidents": [], "total": 0}


@router.get("/incidents/{incident_id}")
async def get_incident_detail(incident_id: str):
    """Get single incident detail by ID."""
    # TODO: Day 5 — query Chroma metadata by incident ID
    return {"incident_id": incident_id, "detail": None}
