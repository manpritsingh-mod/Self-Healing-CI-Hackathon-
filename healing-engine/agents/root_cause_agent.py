"""
Root Cause Agent — Tier 2 (LLM call #1).
Takes Tier 1 data (parsed logs + git diff) and asks the LLM
to identify the root cause of the build failure.

This is the first LLM call in the pipeline.
Output: RootCauseAnalysis(root_cause, error_category, affected_file, severity, confidence)
"""

import logging
from agents.base_agent import BaseAgent
from models.schemas import RootCauseAnalysis, ErrorClass
from services.ai_service import ai_service
from core.prompt_builder import prompt_builder
from core.token_budget import token_budget

logger = logging.getLogger(__name__)


class RootCauseAgent(BaseAgent):
    """Diagnoses the root cause of a build failure using LLM."""

    def __init__(self):
        super().__init__(
            name="RootCause",
            role="Diagnose CI/CD failure root cause via LLM",
            uses_llm=True,
        )

    async def analyze(
        self,
        error_class: ErrorClass,
        parsed_logs: dict,
        git_diff: dict = None,
        vector_context: list = None,
    ) -> RootCauseAnalysis:
        """
        Call LLM to diagnose root cause.

        Args:
            error_class: Pre-classified error type (from hybrid classifier)
            parsed_logs: Output from Log Parser Agent (or dict with the fields)
            git_diff: Output from Git Diff Agent (commit info)
            vector_context: Similar past errors from Vector DB

        Returns:
            RootCauseAnalysis with root_cause, category, severity, confidence
        """
        # Check token budget before LLM call
        estimated_tokens = 1500  # Root cause analysis typically uses ~1500 tokens
        if not token_budget.can_spend(estimated_tokens, ai_service.provider):
            self.logger.warning("Token budget exhausted. Returning empty analysis.")
            return RootCauseAnalysis(
                root_cause="Token budget exhausted — cannot analyze",
                error_category=error_class,
                severity="MEDIUM",
                confidence=0,
            )

        # Extract fields from parsed_logs
        if hasattr(parsed_logs, "error_lines"):
            error_lines = parsed_logs.error_lines
            stack_traces = parsed_logs.stack_traces
            last_50_lines = parsed_logs.last_50_lines
        else:
            error_lines = parsed_logs.get("error_lines", [])
            stack_traces = parsed_logs.get("stack_traces", [])
            last_50_lines = parsed_logs.get("last_50_lines", "")

        # Extract git_diff fields
        git_diff_data = None
        if git_diff:
            if hasattr(git_diff, "commit_hash"):
                git_diff_data = {
                    "commit_hash": git_diff.commit_hash,
                    "author": git_diff.author,
                    "message": git_diff.message,
                    "files_changed": git_diff.files_changed,
                }
            else:
                git_diff_data = git_diff

        # Build dynamic prompt
        system_role, user_prompt = prompt_builder.build_root_cause_prompt(
            error_class=error_class,
            error_lines=error_lines,
            stack_traces=stack_traces,
            last_50_lines=last_50_lines,
            git_diff=git_diff_data,
            vector_context=vector_context,
        )

        # Call LLM with JSON hardening + retry
        response = await ai_service.ask_for_json(
            prompt=user_prompt,
            system_role=system_role,
            required_keys=[
                "root_cause",
                "error_category",
                "affected_file",
                "affected_line",
                "severity",
                "confidence",
            ],
            max_tokens=1024,
            temperature=0.3,
            max_json_retries=2,
        )

        # Track tokens
        tokens_used = response.get("tokens_used", 0)
        token_budget.spend(tokens_used, response.get("provider", ""))

        if not response.get("success"):
            self.logger.error("LLM call failed for root cause analysis")
            return RootCauseAnalysis(
                root_cause="LLM call failed — unable to diagnose",
                error_category=error_class,
                severity="HIGH",
                confidence=0,
            )

        # Structured response (or None after retry exhaustion)
        parsed = response.get("parsed")

        if parsed:
            # Map error_category string to enum
            category_str = parsed.get("error_category", "UNKNOWN")
            try:
                category = ErrorClass(category_str)
            except ValueError:
                category = error_class  # Fall back to classifier's decision

            return RootCauseAnalysis(
                root_cause=parsed.get("root_cause") or "Could not determine root cause",
                error_category=category,
                affected_file=parsed.get("affected_file"),
                affected_line=parsed.get("affected_line"),
                severity=parsed.get("severity") or "MEDIUM",
                confidence=parsed.get("confidence") or 50,
            )
        else:
            # LLM returned unstructured text — use it as-is
            self.logger.warning("Could not parse JSON from LLM, using raw text as root cause")
            return RootCauseAnalysis(
                root_cause=response["content"][:500],
                error_category=error_class,
                severity="MEDIUM",
                confidence=40,
            )
