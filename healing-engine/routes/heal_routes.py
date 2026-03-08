"""
Heal Routes — Direct API for triggering and checking healing events.
POST /api/heal              → Trigger healing for a build
GET  /api/heal/{id}/status  → Check healing progress
GET  /api/heal/{id}/result  → Get healing result
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from models.schemas import HealRequest, HealResponse, Incident
from agents.detection_agent import detection_agent
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Healing"])

# In-memory store for tracking healing events
_healing_store: dict[str, dict] = {}


async def _run_heal(request: HealRequest, healing_id: str):
    """Background task: run the healing pipeline via Detection Agent."""
    _healing_store[healing_id]["status"] = "running"
    logger.info(f"[HEAL] Background task started: {healing_id}")

    try:
        incident = await detection_agent.run(
            job_name=request.job_name,
            build_number=request.build_number,
            raw_logs=request.logs or None,
        )

        _healing_store[healing_id]["status"] = "done"
        _healing_store[healing_id]["result"] = {
            "id": incident.id,
            "job_name": incident.job_name,
            "build_number": incident.build_number,
            "error_class": incident.error_class.value,
            "classification": incident.classification.value,
            "root_cause": incident.root_cause.root_cause if incident.root_cause else None,
            "affected_file": incident.root_cause.affected_file if incident.root_cause else None,
            "affected_line": incident.root_cause.affected_line if incident.root_cause else None,
            "severity": incident.root_cause.severity if incident.root_cause else None,
            "fix_description": incident.final_fix.fix_description if incident.final_fix else None,
            "fix_code": incident.final_fix.fix_code if incident.final_fix else None,
            "fix_steps": incident.final_fix.fix_steps if incident.final_fix else [],
            "final_confidence": incident.final_confidence,
            "resolution_mode": incident.resolution_mode.value,
            "loop_count": len(incident.loop_attempts),
            "agents_used": incident.agents_used,
            "total_tokens_used": incident.total_tokens_used,
            "processing_time_seconds": incident.processing_time_seconds,
        }

        logger.info(
            f"[HEAL] Complete: {healing_id} → "
            f"{incident.resolution_mode.value} ({incident.final_confidence}%)"
        )

    except Exception as e:
        logger.error(f"[HEAL] Failed: {healing_id} → {e}")
        _healing_store[healing_id]["status"] = "error"
        _healing_store[healing_id]["error"] = str(e)


@router.post("/heal", response_model=HealResponse)
async def trigger_healing(request: HealRequest, background_tasks: BackgroundTasks):
    """
    Trigger healing for a specific build.
    Called by Jenkins plugin's selfHeal() pipeline step or manually.
    """
    healing_id = str(uuid.uuid4())[:8]

    logger.info(
        f"[HEAL] Triggered: job={request.job_name} "
        f"build=#{request.build_number} healing_id={healing_id}"
    )

    # Store initial state
    _healing_store[healing_id] = {
        "status": "queued",
        "job_name": request.job_name,
        "build_number": request.build_number,
        "result": None,
    }

    # Trigger healing pipeline in background
    background_tasks.add_task(_run_heal, request, healing_id)

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
    if entry["status"] not in ("done", "error"):
        return {"healing_id": healing_id, "status": entry["status"], "result": None}

    return {
        "healing_id": healing_id,
        "status": entry["status"],
        "result": entry.get("result"),
        "error": entry.get("error"),
    }
