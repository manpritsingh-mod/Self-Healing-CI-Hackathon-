"""
Heal Routes — Direct API for triggering and checking healing events.
POST /api/heal              → Trigger healing for a build
GET  /api/heal/{id}/status  → Check healing progress
GET  /api/heal/{id}/result  → Get healing result
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from models.schemas import HealRequest, HealResponse, Incident
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Healing"])

# In-memory store for tracking healing events (replaced by Chroma metadata later)
_healing_store: dict[str, dict] = {}


@router.post("/heal", response_model=HealResponse)
async def trigger_healing(request: HealRequest, background_tasks: BackgroundTasks):
    """
    Trigger healing for a specific build.
    Called by Jenkins plugin's selfHeal() pipeline step.
    """
    healing_id = str(uuid.uuid4())[:8]

    logger.info(
        f"[HEAL] Triggered: job={request.job_name} "
        f"build=#{request.build_number} healing_id={healing_id}"
    )

    # Store initial state
    _healing_store[healing_id] = {
        "status": "processing",
        "job_name": request.job_name,
        "build_number": request.build_number,
        "result": None,
    }

    # TODO: Day 4 — trigger orchestrator in background
    # background_tasks.add_task(
    #     orchestrator.orchestrate,
    #     request.job_name,
    #     request.build_number,
    #     request.logs,
    #     healing_id
    # )

    return HealResponse(healing_id=healing_id, status="processing")


@router.get("/heal/{healing_id}/status")
async def get_healing_status(healing_id: str):
    """Check the current status of a healing event."""
    if healing_id not in _healing_store:
        raise HTTPException(status_code=404, detail=f"Healing ID {healing_id} not found")

    entry = _healing_store[healing_id]
    return {
        "healing_id": healing_id,
        "status": entry["status"],
        "job_name": entry["job_name"],
        "build_number": entry["build_number"],
    }


@router.get("/heal/{healing_id}/result")
async def get_healing_result(healing_id: str):
    """Get the full result of a completed healing event."""
    if healing_id not in _healing_store:
        raise HTTPException(status_code=404, detail=f"Healing ID {healing_id} not found")

    entry = _healing_store[healing_id]
    if entry["status"] != "done":
        return {"healing_id": healing_id, "status": entry["status"], "result": None}

    return {"healing_id": healing_id, "status": "done", "result": entry["result"]}
