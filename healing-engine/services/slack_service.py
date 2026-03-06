"""
Slack Service — Rich notification messages to Slack via webhook.
Formats incidents into structured Slack blocks with:
  - Color-coded sidebar (green=READY, yellow=ESCALATION, blue=CACHED)
  - Root cause, fix description, fix code
  - Confidence score ALWAYS shown at the end
"""

import httpx
import logging
from models.schemas import Incident, ResolutionMode
from config import SLACK_WEBHOOK_URL

logger = logging.getLogger(__name__)


class SlackService:
    """Sends rich Slack notifications for healing events."""

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15.0)

    async def send_incident(self, incident: Incident) -> bool:
        """
        Send a formatted incident notification to Slack.
        Returns True if sent successfully.
        """
        if not SLACK_WEBHOOK_URL:
            logger.warning("[SLACK] No webhook URL configured. Skipping notification.")
            return False

        payload = self._build_payload(incident)

        try:
            response = await self._client.post(SLACK_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            logger.info(f"[SLACK] Notification sent for {incident.job_name} #{incident.build_number}")
            return True
        except httpx.HTTPError as e:
            logger.error(f"[SLACK] Failed to send notification: {e}")
            return False

    def _build_payload(self, incident: Incident) -> dict:
        """Build Slack message payload with blocks."""

        # Color based on resolution mode
        color_map = {
            ResolutionMode.READY_FIX: "#36a64f",   # Green
            ResolutionMode.ESCALATION: "#ff9900",   # Orange
            ResolutionMode.CACHED: "#439FE0",       # Blue
        }
        color = color_map.get(incident.resolution_mode, "#cccccc")

        # Mode emoji
        mode_map = {
            ResolutionMode.READY_FIX: "✅ READY FIX",
            ResolutionMode.ESCALATION: "⚠️ ESCALATION",
            ResolutionMode.CACHED: "💾 CACHED FIX",
        }
        mode_text = mode_map.get(incident.resolution_mode, "Unknown")

        # Root cause text
        root_cause_text = "N/A"
        if incident.root_cause:
            root_cause_text = incident.root_cause.root_cause

        # Fix text
        fix_text = "No fix available"
        fix_code = None
        if incident.final_fix:
            fix_text = incident.final_fix.fix_description
            fix_code = incident.final_fix.fix_code

        # Build fields
        fields = [
            {"title": "Job", "value": incident.job_name, "short": True},
            {"title": "Build", "value": f"#{incident.build_number}", "short": True},
            {"title": "Error Class", "value": incident.error_class.value, "short": True},
            {"title": "Status", "value": mode_text, "short": True},
            {"title": "Root Cause", "value": root_cause_text, "short": False},
            {"title": "Fix", "value": fix_text, "short": False},
        ]

        if fix_code:
            fields.append({"title": "Fix Code", "value": f"```{fix_code}```", "short": False})

        if incident.loop_attempts:
            loop_summary = " → ".join(
                f"Loop {a.loop_no}: {a.confidence}%"
                for a in incident.loop_attempts
            )
            fields.append({"title": "Confidence Loop", "value": loop_summary, "short": False})

        # CONFIDENCE ALWAYS AT THE END
        fields.append({
            "title": "🎯 AI Confidence",
            "value": f"*{incident.final_confidence}%*",
            "short": True,
        })

        fields.append({
            "title": "Processing Time",
            "value": f"{incident.processing_time_seconds}s",
            "short": True,
        })

        return {
            "attachments": [{
                "color": color,
                "title": f"🔧 Self-Healing CI/CD — {incident.job_name} #{incident.build_number}",
                "fields": fields,
                "footer": f"Agents: {', '.join(incident.agents_used)} | Tokens: {incident.total_tokens_used}",
                "ts": int(incident.timestamp.timestamp()) if incident.timestamp else None,
            }]
        }

    async def close(self):
        await self._client.aclose()


# Singleton instance
slack_service = SlackService()
