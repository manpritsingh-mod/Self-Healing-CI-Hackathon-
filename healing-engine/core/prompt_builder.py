"""
Prompt Builder — Dynamic prompt generation for LLM-calling agents.
NO static prompts. Every prompt is assembled from:
  1. Role fragment (based on error class)
  2. Context data (parsed logs, git diff, vector matches)
  3. Focus template (what the LLM should produce)
  4. Output format (JSON schema for structured responses)

Used by: Root Cause Agent, Fix Agent, Validator Agent.
"""

import logging
from models.schemas import ErrorClass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Role Fragments — One per error class + UNKNOWN fallback
# ═══════════════════════════════════════════════════════════

ROLE_FRAGMENTS = {
    ErrorClass.COMPILATION: (
        "You are a senior build engineer specializing in compilation errors. "
        "You have deep expertise in Java (javac, Maven, Gradle), C/C++ (gcc, make), "
        "and TypeScript/JavaScript build systems. You understand symbol resolution, "
        "type systems, and classpath configuration."
    ),
    ErrorClass.TEST_FAILURE: (
        "You are a senior test engineer specializing in test failure analysis. "
        "You have deep expertise in JUnit, TestNG, pytest, Jest, and Mocha. "
        "You understand assertion patterns, test data issues, mocking problems, "
        "and flaky test detection."
    ),
    ErrorClass.DEPENDENCY: (
        "You are a senior DevOps engineer specializing in dependency management. "
        "You have deep expertise in Maven, Gradle, npm, pip, and NuGet. "
        "You understand version resolution, repository configuration, "
        "transitive dependencies, and lock files."
    ),
    ErrorClass.CONFIG: (
        "You are a senior infrastructure engineer specializing in configuration. "
        "You have deep expertise in environment variables, YAML/properties files, "
        "secrets management, and deployment configuration. You understand "
        "12-factor app principles and config-as-code."
    ),
    ErrorClass.UNKNOWN: (
        "You are a senior CI/CD engineer with broad expertise across build systems, "
        "testing frameworks, dependency managers, and infrastructure. "
        "Analyze the error carefully to identify the root cause category."
    ),
}


# ═══════════════════════════════════════════════════════════
# Prompt Builder Class
# ═══════════════════════════════════════════════════════════

class PromptBuilder:
    """Assembles dynamic prompts from role + context + focus + output format."""

    def build_root_cause_prompt(
        self,
        error_class: ErrorClass,
        error_lines: list[str],
        stack_traces: list[str],
        last_50_lines: str,
        git_diff: dict = None,
        vector_context: list[dict] = None,
    ) -> tuple[str, str]:
        """
        Build prompt for Root Cause Agent.

        Returns: (system_role, user_prompt)
        """
        system_role = ROLE_FRAGMENTS.get(error_class, ROLE_FRAGMENTS[ErrorClass.UNKNOWN])

        # Build context sections
        sections = []

        sections.append("## Error Lines\n```\n" + "\n".join(error_lines[:15]) + "\n```")

        if stack_traces:
            sections.append("## Stack Traces\n```\n" + "\n".join(stack_traces[:5]) + "\n```")

        if git_diff and git_diff.get("commit_hash"):
            sections.append(
                f"## Recent Commit\n"
                f"- Hash: {git_diff['commit_hash']}\n"
                f"- Author: {git_diff.get('author', 'unknown')}\n"
                f"- Message: {git_diff.get('message', '')}\n"
                f"- Files changed: {', '.join(git_diff.get('files_changed', [])[:5])}"
            )

        if vector_context:
            past_fixes = []
            for match in vector_context[:2]:
                past_fixes.append(
                    f"- Similar error (similarity: {match['similarity']}): "
                    f"{match.get('root_cause', 'N/A')}\n"
                    f"  Fix: {match.get('fix', 'N/A')}"
                )
            sections.append("## Similar Past Errors\n" + "\n".join(past_fixes))

        sections.append("## Last 50 Lines of Log\n```\n" + last_50_lines[-2000:] + "\n```")

        user_prompt = (
            "Analyze this CI/CD build failure and identify the root cause.\n\n"
            + "\n\n".join(sections)
            + "\n\n## Required Output (JSON)\n"
            "Respond with ONLY this JSON:\n"
            "```json\n"
            "{\n"
            '  "root_cause": "Clear one-line description of what caused the failure",\n'
            '  "error_category": "COMPILATION|TEST_FAILURE|DEPENDENCY|CONFIG|UNKNOWN",\n'
            '  "affected_file": "path/to/affected/file.java or null",\n'
            '  "affected_line": 42,\n'
            '  "severity": "HIGH|MEDIUM|LOW",\n'
            '  "confidence": 85\n'
            "}\n"
            "```"
        )

        return system_role, user_prompt

    def build_fix_prompt(
        self,
        error_class: ErrorClass,
        root_cause: dict,
        error_lines: list[str],
        validator_feedback: str = None,
    ) -> tuple[str, str]:
        """
        Build prompt for Fix Agent.
        On subsequent loops, includes validator feedback for improvement.

        Returns: (system_role, user_prompt)
        """
        system_role = (
            ROLE_FRAGMENTS.get(error_class, ROLE_FRAGMENTS[ErrorClass.UNKNOWN])
            + " You also provide precise, actionable code fixes."
        )

        sections = [
            f"## Root Cause\n{root_cause.get('root_cause', 'Unknown')}",
            f"## Error Category\n{root_cause.get('error_category', 'UNKNOWN')}",
            f"## Affected File\n{root_cause.get('affected_file', 'Unknown')}",
            "## Error Lines\n```\n" + "\n".join(error_lines[:10]) + "\n```",
        ]

        if validator_feedback:
            sections.append(
                f"## Previous Fix Was Rejected\nValidator feedback:\n{validator_feedback}\n\n"
                "Please provide an IMPROVED fix addressing this feedback."
            )

        user_prompt = (
            "Provide a fix for this CI/CD failure.\n\n"
            + "\n\n".join(sections)
            + "\n\n## Required Output (JSON)\n"
            "Respond with ONLY this JSON:\n"
            "```json\n"
            "{\n"
            '  "fix_description": "Clear description of the fix",\n'
            '  "fix_code": "The actual code change or command to fix the issue",\n'
            '  "fix_steps": ["Step 1", "Step 2"]\n'
            "}\n"
            "```"
        )

        return system_role, user_prompt

    def build_validator_prompt(
        self,
        error_class: ErrorClass,
        root_cause: dict,
        proposed_fix: dict,
        error_lines: list[str],
    ) -> tuple[str, str]:
        """
        Build prompt for Validator Agent.
        Reviews the proposed fix and provides confidence score.

        Returns: (system_role, user_prompt)
        """
        system_role = (
            "You are a senior code reviewer and validation expert. "
            "Your job is to critically evaluate proposed fixes for CI/CD failures. "
            "Be strict: only approve fixes you are confident will actually resolve the issue. "
            "If the fix is incomplete, addresses the wrong problem, or could cause side effects, reject it."
        )

        user_prompt = (
            "Review this proposed fix for a CI/CD failure.\n\n"
            f"## Root Cause\n{root_cause.get('root_cause', 'Unknown')}\n\n"
            f"## Error Category\n{root_cause.get('error_category', 'UNKNOWN')}\n\n"
            "## Original Errors\n```\n" + "\n".join(error_lines[:10]) + "\n```\n\n"
            f"## Proposed Fix\n"
            f"**Description**: {proposed_fix.get('fix_description', '')}\n\n"
            f"**Code**:\n```\n{proposed_fix.get('fix_code', 'N/A')}\n```\n\n"
            f"**Steps**: {', '.join(proposed_fix.get('fix_steps', []))}\n\n"
            "## Required Output (JSON)\n"
            "Respond with ONLY this JSON:\n"
            "```json\n"
            "{\n"
            '  "approved": true or false,\n'
            '  "feedback": "Detailed feedback on the fix quality",\n'
            '  "confidence": 85\n'
            "}\n"
            "```\n\n"
            "IMPORTANT: Only set confidence >= 90 if you are CERTAIN the fix will resolve the issue."
        )

        return system_role, user_prompt


# Singleton instance
prompt_builder = PromptBuilder()
