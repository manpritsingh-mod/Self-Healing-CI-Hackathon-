"""
Config Routes — System configuration and monitoring endpoints.
GET  /api/config         → Engine configuration
GET  /api/tokens         → Token usage today
GET  /api/incidents      → Incident summaries from Chroma metadata
GET  /api/incidents/{id} → Single incident detail
GET  /api/stats          → Vector DB statistics
"""

from fastapi import APIRouter
from config import (
    AI_PROVIDER,
    TOKEN_DAILY_LIMIT,
    CONFIDENCE_THRESHOLD,
    MAX_LOOPS,
    PUBLIC_ENGINE_URL,
    GITHUB_OWNER,
    GITHUB_REPO,
)
from core.token_budget import token_budget
from services.slack_service import slack_service
from services.vector_db_service import vector_db_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Configuration"])


@router.get("/tokens")
async def get_token_usage():
    """Get current daily token usage and remaining budget."""
    return token_budget.get_status()


@router.get("/config")
async def get_config():
    """Get current engine configuration (non-sensitive)."""
    return {
        "ai_provider": AI_PROVIDER,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "max_loops": MAX_LOOPS,
        "token_daily_limit": TOKEN_DAILY_LIMIT,
        "public_engine_url": PUBLIC_ENGINE_URL,
        "github_repo": f"{GITHUB_OWNER}/{GITHUB_REPO}" if GITHUB_OWNER and GITHUB_REPO else "",
    }


@router.get("/incidents")
async def get_incidents():
    """Get recent incident summaries from Chroma metadata."""
    incidents = await vector_db_service.get_incidents(limit=20)
    return {"incidents": incidents, "total": len(incidents)}


@router.get("/incidents/{incident_id}")
async def get_incident_detail(incident_id: str):
    """Get single incident detail by ID."""
    detail = await vector_db_service.get_incident_by_id(incident_id)
    if detail is None:
        return {"incident_id": incident_id, "detail": None, "found": False}
    return {"incident_id": incident_id, "detail": detail, "found": True}


@router.get("/slack/last")
async def get_last_slack_notification():
    """Inspect the most recent Slack payload and delivery status."""
    return slack_service.get_last_notification()


@router.get("/stats")
async def get_stats():
    """Get Vector DB and system statistics."""
    return {
        "vector_db": vector_db_service.get_stats(),
        "token_budget": token_budget.get_status(),
        "ai_provider": AI_PROVIDER,
    }
