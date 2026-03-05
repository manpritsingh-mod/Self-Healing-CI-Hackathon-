"""
Git Diff Agent — Tier 1 (no LLM).
Fetches recent commit info from Jenkins build to provide change context.

Output: CommitData(commit_hash, author, message, files_changed)
"""

from agents.base_agent import BaseAgent
from models.schemas import CommitData
from services.jenkins_service import jenkins_service


class GitDiffAgent(BaseAgent):
    """Fetches git commit data from Jenkins to add change context to diagnosis."""

    def __init__(self):
        super().__init__(
            name="GitDiff",
            role="Fetch recent commit info for change context",
            uses_llm=False,
        )

    async def analyze(self, job_name: str, build_number: int) -> CommitData:
        """
        Get the most recent commit info associated with a Jenkins build.

        Args:
            job_name: Jenkins job/pipeline name
            build_number: Build number

        Returns:
            CommitData with commit hash, author, message, and changed files
        """
        try:
            changes = await jenkins_service.get_last_changes(job_name, build_number)

            commit_data = CommitData(
                commit_hash=changes.get("commit_hash"),
                author=changes.get("author"),
                message=changes.get("message"),
                files_changed=changes.get("files_changed", []),
            )

            if commit_data.commit_hash:
                self.logger.info(
                    f"Commit: {commit_data.commit_hash[:8]} by {commit_data.author} "
                    f"({len(commit_data.files_changed)} files changed)"
                )
            else:
                self.logger.info("No commit data found for this build")

            return commit_data

        except Exception as e:
            self.logger.warning(f"Could not fetch git data: {e}")
            return CommitData()
