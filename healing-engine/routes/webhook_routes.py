"""
Webhook Routes — Receives Jenkins failure notifications.
POST /webhook/jenkins  → Detection Agent entry point
"""

from fastapi import APIRouter, BackgroundTasks
from models.schemas import WebhookPayload, HealResponse
from agents.detection_agent import detection_agent
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Webhooks"])


async def _run_healing(job_name: str, build_number: int, raw_logs: str, healing_id: str):
    """Background task: run the full healing pipeline."""
    logger.info(f"[WEBHOOK] Background healing started: {healing_id}")
    try:
        incident = await detection_agent.run(
            job_name=job_name,
            build_number=build_number,
            raw_logs=raw_logs or None,
        )
        logger.info(
            f"[WEBHOOK] Healing complete: {healing_id} → "
            f"{incident.resolution_mode.value} ({incident.final_confidence}%)"
        )
    except Exception as e:
        logger.error(f"[WEBHOOK] Healing failed: {healing_id} → {e}")


@router.post("/webhook/jenkins", response_model=HealResponse)
async def jenkins_webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    """
    Receives Jenkins build failure webhook.
    Triggers healing pipeline in background and returns tracking ID immediately.
    """
    healing_id = str(uuid.uuid4())[:8]

    # Extract job info from webhook payload
    job_name = payload.name or "unknown"
    build_info = payload.build or {}
    build_number = build_info.get("number", 0)
    build_status = build_info.get("status", "")
    build_log = build_info.get("log", "")

    logger.info(
        f"[WEBHOOK] Received: job={job_name} build=#{build_number} "
        f"status={build_status} healing_id={healing_id}"
    )

    # Only process failures
    if build_status and build_status.upper() not in ("FAILURE", "FAILED", "UNSTABLE"):
        return HealResponse(healing_id=healing_id, status="skipped_not_failure")

    # Trigger healing pipeline in background
    background_tasks.add_task(_run_healing, job_name, build_number, build_log, healing_id)

    return HealResponse(healing_id=healing_id, status="processing")
