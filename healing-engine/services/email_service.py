"""
Email Service — SMTP email notifications for healing events.
Sends formatted HTML emails with incident details.
Used as secondary notification channel alongside Slack.
"""

import aiosmtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from models.schemas import Incident, ResolutionMode
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, NOTIFICATION_EMAIL

logger = logging.getLogger(__name__)


class EmailService:
    """Sends email notifications for healing events via SMTP."""

    async def send_incident(self, incident: Incident) -> bool:
        """Send an HTML email notification for an incident."""
        if not all([SMTP_USER, SMTP_PASSWORD, NOTIFICATION_EMAIL]):
            logger.warning("[EMAIL] SMTP not fully configured. Skipping email.")
            return False

        try:
            msg = self._build_email(incident)

            await aiosmtplib.send(
                msg,
                hostname=SMTP_HOST,
                port=SMTP_PORT,
                username=SMTP_USER,
                password=SMTP_PASSWORD,
                use_tls=False,
                start_tls=True,
            )

            logger.info(f"[EMAIL] Sent to {NOTIFICATION_EMAIL}")
            return True

        except Exception as e:
            logger.error(f"[EMAIL] Failed to send: {e}")
            return False

    def _build_email(self, incident: Incident) -> MIMEMultipart:
        """Build HTML email message."""
        mode_emoji = {
            ResolutionMode.READY_FIX: "✅",
            ResolutionMode.ESCALATION: "⚠️",
            ResolutionMode.CACHED: "💾",
        }
        emoji = mode_emoji.get(incident.resolution_mode, "🔧")

        subject = (
            f"{emoji} [{incident.resolution_mode.value}] "
            f"{incident.job_name} #{incident.build_number} — "
            f"Confidence: {incident.final_confidence}%"
        )

        # Root cause
        root_cause = "N/A"
        if incident.root_cause:
            root_cause = incident.root_cause.root_cause

        # Fix
        fix_desc = "No fix available"
        fix_code = ""
        if incident.final_fix:
            fix_desc = incident.final_fix.fix_description
            fix_code = incident.final_fix.fix_code or ""

        # Loop history
        loop_html = ""
        if incident.loop_attempts:
            rows = "".join(
                f"<tr><td>Loop {a.loop_no}</td><td>{a.confidence}%</td>"
                f"<td>{a.validator_feedback[:100]}</td></tr>"
                for a in incident.loop_attempts
            )
            loop_html = f"""
            <h3>Confidence Loop History</h3>
            <table border="1" cellpadding="6" cellspacing="0">
                <tr><th>Loop</th><th>Confidence</th><th>Feedback</th></tr>
                {rows}
            </table>
            """

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px;">
            <h2>{emoji} Self-Healing CI/CD Report</h2>
            <table cellpadding="4">
                <tr><td><b>Job</b></td><td>{incident.job_name}</td></tr>
                <tr><td><b>Build</b></td><td>#{incident.build_number}</td></tr>
                <tr><td><b>Error Class</b></td><td>{incident.error_class.value}</td></tr>
                <tr><td><b>Status</b></td><td>{incident.resolution_mode.value}</td></tr>
                <tr><td><b>Time</b></td><td>{incident.processing_time_seconds}s</td></tr>
            </table>

            <h3>Root Cause</h3>
            <p>{root_cause}</p>

            <h3>Fix</h3>
            <p>{fix_desc}</p>
            {"<pre style='background:#f5f5f5;padding:12px;'>" + fix_code + "</pre>" if fix_code else ""}

            {loop_html}

            <h2 style="color:#2e86c1;">🎯 AI Confidence: {incident.final_confidence}%</h2>

            <hr>
            <p style="color:#888; font-size:12px;">
                Agents: {", ".join(incident.agents_used)} |
                Tokens: {incident.total_tokens_used}
            </p>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFICATION_EMAIL
        msg.attach(MIMEText(html, "html"))

        return msg


# Singleton instance
email_service = EmailService()
