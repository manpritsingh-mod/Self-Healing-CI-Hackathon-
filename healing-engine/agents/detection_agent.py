"""
Detection Agent — Tier 0 (entry point).
Listens for build failures and triggers the healing pipeline.

Entry points:
  1. Jenkins webhook (POST /webhook/jenkins)
  2. Direct API call (POST /api/heal)

This agent does NOT call LLM. It's a simple intake/router.
"""

import logging
from agents.base_agent import BaseAgent
from agents.orchestrator_agent import OrchestratorAgent
from models.schemas import Incident

logger = logging.getLogger(__name__)


class DetectionAgent(BaseAgent):
    """Detects build failures and triggers the orchestrator."""

    def __init__(self):
        super().__init__(
            name="Detection",
            role="Detect build failures and trigger healing pipeline",
            uses_llm=False,
        )
        self.orchestrator = OrchestratorAgent()

    async def analyze(
        self,
        job_name: str,
        build_number: int,
        raw_logs: str = None,
    ) -> Incident:
        """
        Entry point for the healing pipeline.

        Args:
            job_name: Jenkins job/pipeline name
            build_number: Build number that failed
            raw_logs: Optional raw console output

        Returns:
            Complete Incident from the orchestrator
        """
        self.logger.info(
            f"Build failure detected: {job_name} #{build_number}"
        )

        # Validate inputs
        if not job_name:
            self.logger.error("No job name provided")
            return Incident(job_name="unknown", build_number=0)

        if build_number <= 0:
            self.logger.error(f"Invalid build number: {build_number}")
            return Incident(job_name=job_name, build_number=build_number)

        # Hand off to orchestrator
        try:
            incident = await self.orchestrator.run(
                job_name=job_name,
                build_number=build_number,
                raw_logs=raw_logs,
            )
            return incident

        except Exception as e:
            self.logger.error(f"Orchestrator failed: {e}")
            return Incident(
                job_name=job_name,
                build_number=build_number,
                agents_used=["Detection"],
            )


# Singleton instance
detection_agent = DetectionAgent()
