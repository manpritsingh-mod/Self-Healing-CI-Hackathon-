"""
Notify Agent — Final agent in the pipeline.
After the Orchestrator produces an Incident, the Notify Agent:
  1. Sends Slack notification
  2. Sends email notification
  3. Stores incident in ChromaDB metadata (incident memory)

This is the ONLY agent that writes to external systems.
"""

import json
import logging
from agents.base_agent import BaseAgent
from models.schemas import Incident
from services.slack_service import slack_service
from services.email_service import email_service
from services.vector_db_service import vector_db_service

logger = logging.getLogger(__name__)


class NotifyAgent(BaseAgent):
    """Sends notifications and persists incident memory."""

    def __init__(self):
        super().__init__(
            name="Notify",
            role="Send notifications (Slack + Email) and persist incident memory",
            uses_llm=False,
        )

    async def analyze(self, incident: Incident):
        """
        Send notifications and store incident in ChromaDB.

        Args:
            incident: Complete Incident from the Orchestrator
        """
        self.logger.info(
            f"Processing notification for {incident.job_name} "
            f"#{incident.build_number} ({incident.resolution_mode.value})"
        )

        # ── 1. Send Slack notification ──
        slack_sent = await slack_service.send_incident(incident)
        self.logger.info(f"Slack: {'✅ Sent' if slack_sent else '⏭️ Skipped'}")

        # ── 2. Send email notification ──
        email_sent = await email_service.send_incident(incident)
        self.logger.info(f"Email: {'✅ Sent' if email_sent else '⏭️ Skipped'}")

        # ── 3. Store incident in ChromaDB (incident memory) ──
        await self._store_incident_memory(incident)

        self.logger.info(
            f"Notification complete: Slack={'✅' if slack_sent else '❌'} "
            f"Email={'✅' if email_sent else '❌'} Memory=✅"
        )

    async def _store_incident_memory(self, incident: Incident):
        """Persist incident to ChromaDB for future similarity matching."""
        try:
            # Error text becomes the embedding (for similarity search)
            error_text = ""
            if incident.root_cause:
                error_text = incident.root_cause.root_cause

            # Metadata stores the fix details + incident info
            metadata = {
                "job_name": incident.job_name,
                "build_number": str(incident.build_number),
                "error_class": incident.error_class.value,
                "classification": incident.classification.value,
                "resolution_mode": incident.resolution_mode.value,
                "final_confidence": str(incident.final_confidence),
                "processing_time": str(incident.processing_time_seconds),
                "agents_used": json.dumps(incident.agents_used),
                "total_tokens": str(incident.total_tokens_used),
                "timestamp": incident.timestamp.isoformat() if incident.timestamp else "",
                "root_cause": incident.root_cause.root_cause if incident.root_cause else "",
                "severity": incident.root_cause.severity if incident.root_cause else "",
                "fix_description": incident.final_fix.fix_description if incident.final_fix else "",
                "fix_code": incident.final_fix.fix_code or "" if incident.final_fix else "",
                "fix_steps": json.dumps(incident.final_fix.fix_steps) if incident.final_fix else "[]",
                "loop_count": str(len(incident.loop_attempts)),
            }

            await vector_db_service.store_incident(
                incident_id=incident.id,
                error_text=error_text,
                metadata=metadata,
            )

            self.logger.info(f"Incident {incident.id} stored in ChromaDB")

        except Exception as e:
            self.logger.error(f"Failed to store incident memory: {e}")


# Singleton instance
notify_agent = NotifyAgent()
