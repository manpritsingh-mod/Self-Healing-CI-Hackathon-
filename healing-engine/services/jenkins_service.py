"""
Jenkins Service — REST API client for Jenkins.
Fetches build logs, build info, commit data, and failed stage info.
Used by: Git Diff Agent, Orchestrator, Detection Agent.
"""

import httpx
import logging
from typing import Optional
from config import JENKINS_URL, JENKINS_USER, JENKINS_TOKEN

logger = logging.getLogger(__name__)


class JenkinsService:
    """Client for Jenkins REST API."""

    def __init__(self):
        self._auth = (JENKINS_USER, JENKINS_TOKEN) if JENKINS_TOKEN else None
        self._client = httpx.AsyncClient(
            timeout=30.0,
            auth=self._auth,
        )

    async def get_build_logs(self, job_name: str, build_number: int) -> str:
        """Fetch console output (full log) for a build."""
        url = f"{JENKINS_URL}/job/{job_name}/{build_number}/consoleText"
        logger.info(f"[JENKINS] Fetching logs: {url}")

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            log_text = response.text
            logger.info(f"[JENKINS] Got {len(log_text)} chars of logs")
            return log_text
        except httpx.HTTPError as e:
            logger.error(f"[JENKINS] Failed to fetch logs: {e}")
            return ""

    async def get_build_info(self, job_name: str, build_number: int) -> dict:
        """Fetch build metadata (result, duration, changeSets, etc.)."""
        url = f"{JENKINS_URL}/job/{job_name}/{build_number}/api/json"
        logger.info(f"[JENKINS] Fetching build info: {url}")

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"[JENKINS] Failed to fetch build info: {e}")
            return {}

    async def get_failed_stage(self, job_name: str, build_number: int) -> Optional[str]:
        """
        Get the name of the failed stage from Pipeline workflow API.
        Returns the stage name (e.g., "Build", "Unit Tests") or None.
        """
        url = f"{JENKINS_URL}/job/{job_name}/{build_number}/wfapi/describe"
        logger.info(f"[JENKINS] Fetching stage info: {url}")

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()

            stages = data.get("stages", [])
            for stage in stages:
                if stage.get("status") in ("FAILED", "ERROR", "UNSTABLE"):
                    stage_name = stage.get("name", "unknown")
                    logger.info(f"[JENKINS] Failed stage: '{stage_name}'")
                    return stage_name

            logger.info("[JENKINS] No failed stage found")
            return None
        except httpx.HTTPError as e:
            logger.warning(f"[JENKINS] Could not fetch stages (may not be Pipeline): {e}")
            return None

    async def get_last_changes(self, job_name: str, build_number: int) -> dict:
        """
        Get the last commit info from the build's changeSets.
        Returns: {commit_hash, author, message, files_changed}
        """
        build_info = await self.get_build_info(job_name, build_number)

        change_sets = build_info.get("changeSets", [])
        if not change_sets:
            # Try changeSet (singular) for older Jenkins
            change_set = build_info.get("changeSet", {})
            items = change_set.get("items", [])
        else:
            items = []
            for cs in change_sets:
                items.extend(cs.get("items", []))

        if not items:
            return {
                "commit_hash": None,
                "author": None,
                "message": None,
                "files_changed": [],
            }

        # Get the most recent commit
        last_commit = items[-1]

        # Extract changed file paths
        files = []
        for path_item in last_commit.get("paths", []):
            files.append(path_item.get("file", ""))
        if not files:
            files = [af.get("fullName", af.get("name", "")) for af in last_commit.get("affectedPaths", [])]

        return {
            "commit_hash": last_commit.get("commitId", last_commit.get("id", "")),
            "author": last_commit.get("authorEmail", last_commit.get("author", {}).get("fullName", "")),
            "message": last_commit.get("msg", last_commit.get("comment", "")),
            "files_changed": files,
        }

    async def close(self):
        """Clean up HTTP client."""
        await self._client.aclose()


# Singleton instance
jenkins_service = JenkinsService()
