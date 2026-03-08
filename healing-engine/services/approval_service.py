"""
Approval Service - signed action URL generation and decision tracking.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

from config import APPROVAL_SIGNING_SECRET, PUBLIC_ENGINE_URL

logger = logging.getLogger(__name__)


class ApprovalService:
    """Creates signed approve/decline URLs and tracks approval decisions."""

    def __init__(self):
        self._decisions: dict[str, dict] = {}
        self._secret = APPROVAL_SIGNING_SECRET or "dev-insecure-secret"
        if not APPROVAL_SIGNING_SECRET:
            logger.warning(
                "[APPROVAL] APPROVAL_SIGNING_SECRET not set. Using dev fallback secret."
            )

    def build_action_url(self, incident_id: str, action: str) -> str:
        """Generate a signed URL for a Slack button action."""
        token = self._token_for(incident_id, action)
        query = urlencode({"token": token})
        base = PUBLIC_ENGINE_URL.rstrip("/")
        return f"{base}/api/approvals/{incident_id}/{action}?{query}"

    def verify_action(self, incident_id: str, action: str, token: str) -> bool:
        """Validate signed action token."""
        expected = self._token_for(incident_id, action)
        return hmac.compare_digest(expected, token or "")

    def record_decision(self, incident_id: str, status: str, detail: dict | None = None):
        """Persist the latest decision state in memory."""
        self._decisions[incident_id] = {
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
            "detail": detail or {},
        }

    def get_decision(self, incident_id: str) -> dict | None:
        """Get the decision record for an incident."""
        return self._decisions.get(incident_id)

    def _token_for(self, incident_id: str, action: str) -> str:
        raw = f"{incident_id}:{action}".encode("utf-8")
        secret = self._secret.encode("utf-8")
        return hmac.new(secret, raw, hashlib.sha256).hexdigest()


approval_service = ApprovalService()
