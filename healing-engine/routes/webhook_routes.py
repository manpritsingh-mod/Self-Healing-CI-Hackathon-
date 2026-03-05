"""
Webhook Routes — Receives Jenkins failure notifications.
POST /webhook/jenkins  → Detection Agent entry point
"""

from fastapi import APIRouter, BackgroundTasks
from models.schemas import WebhookPayload, HealResponse
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Webhooks"])


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

    # TODO: Day 4 — trigger orchestrator in background
    # background_tasks.add_task(orchestrator.orchestrate, job_name, build_number, build_log)

    return HealResponse(healing_id=healing_id, status="processing")
