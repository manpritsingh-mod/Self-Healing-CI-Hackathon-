"""
Approval routes for Slack action links.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from config import CONFIDENCE_THRESHOLD
from services.approval_service import approval_service
from services.remediation_service import remediation_service
from services.vector_db_service import vector_db_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Approvals"])


def _html(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<html><body><h2>{title}</h2><p>{body}</p></body></html>",
        status_code=200,
    )


@router.get("/approvals/{incident_id}/approve", response_class=HTMLResponse)
async def approve_incident(incident_id: str, token: str = Query(default="")):
    if not approval_service.verify_action(incident_id, "approve", token):
        raise HTTPException(status_code=403, detail="Invalid approval token")

    previous = approval_service.get_decision(incident_id)
    if previous and previous.get("status") == "APPROVED":
        detail = previous.get("detail", {})
        return _html(
            "Already approved",
            f"PR: {detail.get('pr_url', 'N/A')} | Branch: {detail.get('fix_branch', 'N/A')}",
        )

    incident = await vector_db_service.get_incident_by_id(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    metadata = incident.get("metadata", {})
    confidence = _to_int(metadata.get("final_confidence"))
    if confidence < CONFIDENCE_THRESHOLD:
        return _html(
            "Approval blocked",
            f"Confidence {confidence}% is below threshold {CONFIDENCE_THRESHOLD}%.",
        )

    try:
        result = await remediation_service.execute_approved_fix(incident_id, metadata)
        approval_service.record_decision(incident_id, "APPROVED", result)
        logger.info(
            f"[APPROVAL] Incident {incident_id} approved. PR={result.get('pr_url')} "
            f"branch={result.get('fix_branch')}"
        )
        return _html(
            "Approved",
            (
                f"PR created: {result.get('pr_url')}<br/>"
                f"Fix branch: {result.get('fix_branch')}<br/>"
                f"Jenkins queue: {result.get('jenkins_queue_url') or 'N/A'}"
            ),
        )
    except Exception as exc:
        approval_service.record_decision(incident_id, "FAILED", {"error": str(exc)})
        logger.error(f"[APPROVAL] Incident {incident_id} approval failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Approval automation failed: {exc}")


@router.get("/approvals/{incident_id}/decline", response_class=HTMLResponse)
async def decline_incident(incident_id: str, token: str = Query(default="")):
    if not approval_service.verify_action(incident_id, "decline", token):
        raise HTTPException(status_code=403, detail="Invalid decline token")

    approval_service.record_decision(incident_id, "DECLINED")
    logger.info(f"[APPROVAL] Incident {incident_id} declined by user")
    return _html("Declined", "No PR created and no Jenkins retrigger executed.")


@router.get("/approvals/{incident_id}/status")
async def approval_status(incident_id: str):
    decision = approval_service.get_decision(incident_id)
    if not decision:
        return {"incident_id": incident_id, "status": "PENDING"}
    return {"incident_id": incident_id, **decision}


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
