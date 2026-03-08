"""
Slack notification service for healing incidents.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from config import CONFIDENCE_THRESHOLD, SLACK_WEBHOOK_URL
from models.schemas import Incident, ResolutionMode
from services.approval_service import approval_service

logger = logging.getLogger(__name__)


class SlackService:
    """Send incident updates to Slack webhook and keep last payload for diagnostics."""

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15.0)
        self._last_notification = {
            "status": "never_sent",
            "payload": None,
            "sent_at": None,
            "incident": None,
            "error": None,
        }

    async def send_incident(self, incident: Incident) -> bool:
        payload = self._build_payload(incident)
        if not SLACK_WEBHOOK_URL:
            self._last_notification = {
                "status": "skipped",
                "payload": payload,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "incident": self._incident_summary(incident),
                "error": "No webhook URL configured",
            }
            logger.warning("[SLACK] No webhook URL configured. Skipping notification.")
            return False

        try:
            response = await self._client.post(SLACK_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            self._last_notification = {
                "status": "sent",
                "payload": payload,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "incident": self._incident_summary(incident),
                "error": None,
            }
            logger.info(f"[SLACK] Notification sent for {incident.job_name} #{incident.build_number}")
            return True
        except httpx.HTTPError as exc:
            self._last_notification = {
                "status": "failed",
                "payload": payload,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "incident": self._incident_summary(incident),
                "error": str(exc),
            }
            logger.error(f"[SLACK] Failed to send notification: {exc}")
            return False

    def _build_payload(self, incident: Incident) -> dict:
        color_map = {
            ResolutionMode.READY_FIX: "#36a64f",
            ResolutionMode.ESCALATION: "#ff9900",
            ResolutionMode.CACHED: "#439FE0",
        }
        color = color_map.get(incident.resolution_mode, "#cccccc")

        mode_map = {
            ResolutionMode.READY_FIX: "READY FIX",
            ResolutionMode.ESCALATION: "ESCALATION",
            ResolutionMode.CACHED: "CACHED FIX",
        }
        mode_text = mode_map.get(incident.resolution_mode, "UNKNOWN")

        root_cause_text = incident.root_cause.root_cause if incident.root_cause else "N/A"
        fix_text = incident.final_fix.fix_description if incident.final_fix else "No fix available"
        fix_code = incident.final_fix.fix_code if incident.final_fix else None

        approve_url = approval_service.build_action_url(incident.id, "approve")
        decline_url = approval_service.build_action_url(incident.id, "decline")

        fallback_text = f"🚨 *Self-Healing CI/CD Issue Detected* 🚨\n\n*Job:* {incident.job_name} #{incident.build_number}\n*Status:* {mode_text}\n*Root Cause:* {root_cause_text}\n*Fix:* {fix_text}\n*AI Confidence:* {incident.final_confidence}%"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 Self-Healing Alert: {incident.job_name} #{incident.build_number}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Status:* {mode_text}\n*Error Class:* {incident.error_class.value}\n*Confidence:* {incident.final_confidence}%"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Root Cause:*\n{root_cause_text}\n\n*Proposed Fix:*\n{fix_text}"
                }
            }
        ]

        if fix_code:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Code Change:*\n```\n{fix_code}\n```"
                }
            })

        if incident.loop_attempts:
            loop_summary = " -> ".join(
                f"Loop {attempt.loop_no}: {attempt.confidence}%"
                for attempt in incident.loop_attempts
            )
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"🔄 *Confidence Loop:* {loop_summary}"}]
            })

        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"⏱️ *Processing Time:* {incident.processing_time_seconds}s | 🤖 *Agents:* {', '.join(incident.agents_used)}"}]
        })

        if incident.final_confidence >= CONFIDENCE_THRESHOLD or incident.resolution_mode == ResolutionMode.CACHED:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Accept & Auto-Fix", "emoji": True},
                        "style": "primary",
                        "url": approve_url,
                        "action_id": "approve_fix"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                        "style": "danger",
                        "url": decline_url,
                        "action_id": "reject_fix"
                    }
                ]
            })
        else:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⚠️ *Manual intervention required. Confidence is below threshold.*"}]
            })

        return {"text": fallback_text, "blocks": blocks}

    def _incident_summary(self, incident: Incident) -> dict:
        return {
            "id": incident.id,
            "job_name": incident.job_name,
            "build_number": incident.build_number,
            "resolution_mode": incident.resolution_mode.value,
            "confidence": incident.final_confidence,
        }

    def get_last_notification(self) -> dict:
        return self._last_notification

    async def close(self):
        await self._client.aclose()


slack_service = SlackService()
