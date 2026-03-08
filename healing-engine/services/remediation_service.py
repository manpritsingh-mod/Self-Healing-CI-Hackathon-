"""
Remediation Service - apply approved fix, create PR, and retrigger Jenkins.
"""

from __future__ import annotations

import base64
import logging
import time
from urllib.parse import quote

import httpx

from config import (
    GITHUB_BASE_BRANCH,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_TOKEN,
    JENKINS_TOKEN,
    JENKINS_URL,
    JENKINS_USER,
)

logger = logging.getLogger(__name__)


class RemediationService:
    """Executes approval-time automation: commit fix, PR, and Jenkins retrigger."""

    def __init__(self):
        self._github = httpx.AsyncClient(timeout=30.0)
        self._jenkins = httpx.AsyncClient(
            timeout=30.0,
            auth=(JENKINS_USER, JENKINS_TOKEN) if JENKINS_TOKEN else None,
        )

    async def execute_approved_fix(self, incident_id: str, metadata: dict) -> dict:
        """Apply fix from incident metadata and return automation outputs."""
        self._validate_github_config()

        job_name = (metadata.get("job_name") or "").strip()
        build_number = self._to_int(metadata.get("build_number"))
        affected_file = (metadata.get("affected_file") or "").strip()
        affected_line = self._to_int(metadata.get("affected_line"))
        fix_code = (metadata.get("fix_code") or "").strip()
        fix_description = (metadata.get("fix_description") or "").strip()

        if not affected_file or affected_line <= 0 or not fix_code:
            raise ValueError(
                "Incident is missing affected_file, affected_line, or fix_code required for remediation."
            )

        base_branch = await self._resolve_base_branch(job_name, build_number)
        fix_branch = f"ai-fix/{incident_id}-{int(time.time())}"

        await self._create_fix_branch(base_branch, fix_branch)
        commit = await self._commit_file_fix(
            branch=fix_branch,
            affected_file=affected_file,
            affected_line=affected_line,
            fix_code=fix_code,
            incident_id=incident_id,
        )
        pr = await self._create_pull_request(
            incident_id=incident_id,
            head_branch=fix_branch,
            base_branch=base_branch,
            fix_description=fix_description,
        )
        queue_url = await self._trigger_jenkins_verification(job_name, fix_branch)

        return {
            "incident_id": incident_id,
            "base_branch": base_branch,
            "fix_branch": fix_branch,
            "commit_sha": commit.get("commit", {}).get("sha"),
            "pr_url": pr.get("html_url"),
            "pr_number": pr.get("number"),
            "jenkins_queue_url": queue_url,
            "job_name": job_name,
            "build_number": build_number,
        }

    async def _resolve_base_branch(self, job_name: str, build_number: int) -> str:
        """Prefer the Jenkins REPO_BRANCH parameter, fallback to configured base."""
        if job_name and build_number > 0:
            try:
                job_enc = quote(job_name, safe="")
                info_url = f"{JENKINS_URL}/job/{job_enc}/{build_number}/api/json"
                response = await self._jenkins.get(info_url)
                response.raise_for_status()
                build_info = response.json()
                for action in build_info.get("actions", []):
                    for param in action.get("parameters", []):
                        if param.get("name") == "REPO_BRANCH" and param.get("value"):
                            return str(param["value"])
            except Exception as exc:
                logger.warning(f"[REMEDIATION] Could not infer base branch from Jenkins: {exc}")
        return GITHUB_BASE_BRANCH

    async def _create_fix_branch(self, base_branch: str, fix_branch: str):
        base_ref = await self._github_get(
            f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/ref/heads/{quote(base_branch, safe='')}"
        )
        base_sha = base_ref.get("object", {}).get("sha")
        if not base_sha:
            raise RuntimeError(f"Could not resolve base branch SHA for '{base_branch}'")

        payload = {"ref": f"refs/heads/{fix_branch}", "sha": base_sha}
        response = await self._github.post(
            self._github_url(f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs"),
            headers=self._github_headers(),
            json=payload,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create fix branch '{fix_branch}': {response.status_code} {response.text}"
            )

    async def _commit_file_fix(
        self,
        branch: str,
        affected_file: str,
        affected_line: int,
        fix_code: str,
        incident_id: str,
    ) -> dict:
        path = quote(affected_file.strip("/"), safe="/")
        content_data = await self._github_get(
            f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}?ref={quote(branch, safe='')}"
        )

        current_sha = content_data.get("sha")
        encoded_content = content_data.get("content", "")
        if not current_sha or not encoded_content:
            raise RuntimeError(f"Could not load file content for '{affected_file}'")

        raw = base64.b64decode(encoded_content).decode("utf-8")
        lines = raw.splitlines()
        if affected_line > len(lines):
            raise RuntimeError(
                f"Affected line {affected_line} is outside file length {len(lines)} for {affected_file}"
            )

        original = lines[affected_line - 1]
        indentation = original[: len(original) - len(original.lstrip())]
        lines[affected_line - 1] = indentation + fix_code
        new_content = ("\n".join(lines) + "\n").encode("utf-8")
        new_content_b64 = base64.b64encode(new_content).decode("utf-8")

        payload = {
            "message": f"Apply AI fix for incident {incident_id}",
            "content": new_content_b64,
            "sha": current_sha,
            "branch": branch,
        }
        response = await self._github.put(
            self._github_url(f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"),
            headers=self._github_headers(),
            json=payload,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to commit fix to '{affected_file}': {response.status_code} {response.text}"
            )
        return response.json()

    async def _create_pull_request(
        self,
        incident_id: str,
        head_branch: str,
        base_branch: str,
        fix_description: str,
    ) -> dict:
        payload = {
            "title": f"AI fix for incident {incident_id}",
            "head": head_branch,
            "base": base_branch,
            "body": (
                f"Automated fix generated by Self-Healing CI/CD.\n\n"
                f"- Incident: {incident_id}\n"
                f"- Summary: {fix_description or 'N/A'}\n"
            ),
        }
        response = await self._github.post(
            self._github_url(f"/repos/{GITHUB_OWNER}/{GITHUB_REPO}/pulls"),
            headers=self._github_headers(),
            json=payload,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create PR: {response.status_code} {response.text}")
        return response.json()

    async def _trigger_jenkins_verification(self, job_name: str, branch: str) -> str:
        if not job_name:
            return ""

        headers = await self._jenkins_crumb_headers()
        params = {
            "REPO_BRANCH": branch,
            "SIMULATE_FAILURE": "false",
            "AUTO_HEAL_ON_FAILURE": "false",
        }
        job_enc = quote(job_name, safe="")
        url = f"{JENKINS_URL}/job/{job_enc}/buildWithParameters"
        response = await self._jenkins.post(url, params=params, headers=headers)
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to trigger Jenkins verification for '{job_name}': "
                f"{response.status_code} {response.text}"
            )
        return response.headers.get("Location", "")

    async def _jenkins_crumb_headers(self) -> dict:
        try:
            response = await self._jenkins.get(f"{JENKINS_URL}/crumbIssuer/api/json")
            if response.status_code != 200:
                return {}
            data = response.json()
            return {data["crumbRequestField"]: data["crumb"]}
        except Exception:
            return {}

    def _validate_github_config(self):
        missing = []
        if not GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if not GITHUB_OWNER:
            missing.append("GITHUB_OWNER")
        if not GITHUB_REPO:
            missing.append("GITHUB_REPO")
        if missing:
            raise RuntimeError("Missing required GitHub config: " + ", ".join(missing))

    def _github_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "self-healing-cicd-engine",
        }

    def _github_url(self, path: str) -> str:
        return "https://api.github.com" + path

    async def _github_get(self, path: str) -> dict:
        response = await self._github.get(self._github_url(path), headers=self._github_headers())
        if response.status_code != 200:
            raise RuntimeError(f"GitHub GET failed: {response.status_code} {response.text}")
        return response.json()

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def close(self):
        await self._github.aclose()
        await self._jenkins.aclose()


remediation_service = RemediationService()
