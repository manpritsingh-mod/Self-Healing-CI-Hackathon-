"""
Log Parser Agent — Tier 1 (no LLM).
Extracts error signals from raw Jenkins console output using regex.

Output: ParsedLogs(error_lines, stack_traces, warnings, failed_stage, last_50_lines)
"""

import re
from typing import Optional
from agents.base_agent import BaseAgent
from models.schemas import ParsedLogs

# ── Regex Patterns ───────────────────────────────────────────

ERROR_PATTERNS = [
    r"^\[ERROR\].*",                          # Maven/Gradle [ERROR]
    r"^error:.*",                             # Generic error:
    r"^Error:.*",                             # Capitalized Error:
    r"^FAILURE:.*",                           # Gradle FAILURE:
    r"^FATAL:.*",                             # Jenkins FATAL:
    r".*cannot find symbol.*",                # Java compilation
    r".*incompatible types.*",                # Java type error
    r".*syntax error.*",                      # Generic syntax
    r".*Could not resolve.*",                 # Dependency resolution
    r".*No matching version.*",               # npm/pip version
    r".*ModuleNotFoundError.*",               # Python import
    r".*npm ERR!.*",                          # npm error
    r".*FileNotFoundException.*",             # Missing file
    r".*BUILD FAILURE.*",                     # Maven/Gradle
    r".*BUILD FAILED.*",                      # Alternative
    r".*compilation.*fail.*",                 # Compilation
    r".*Tests run:.*Failures: [1-9].*",       # JUnit test failures
    r".*AssertionError.*",                    # Test assertion
    r".*NullPointerException.*",             # NPE
    r".*Permission denied.*",                # Permission
    r".*connection refused.*",               # Network
    r".*environment variable.*not set.*",    # Missing env var
]

WARNING_PATTERNS = [
    r"^\[WARNING\].*",
    r"^WARNING:.*",
    r"^WARN:.*",
    r".*deprecated.*",
]

STACK_TRACE_PATTERN = r"^\s+at\s+[\w.$]+\([\w.]+:\d+\)"   # Java stack trace line
PYTHON_TRACE_PATTERN = r'^\s+File ".*", line \d+'          # Python traceback


class LogParserAgent(BaseAgent):
    """Parses raw Jenkins logs to extract errors, stack traces, and warnings."""

    def __init__(self):
        super().__init__(
            name="LogParser",
            role="Extract error signals from build logs",
            uses_llm=False,
        )

    async def analyze(self, raw_logs: str, failed_stage: Optional[str] = None) -> ParsedLogs:
        """
        Parse raw logs and extract structured error information.

        Args:
            raw_logs: Full console output from Jenkins build
            failed_stage: Optional stage name from Jenkins API

        Returns:
            ParsedLogs with error_lines, stack_traces, warnings, etc.
        """
        lines = raw_logs.split("\n")

        error_lines = []
        stack_traces = []
        warnings = []
        current_trace = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # End of a stack trace block
                if current_trace:
                    stack_traces.append("\n".join(current_trace))
                    current_trace = []
                continue

            # Check for error patterns
            for pattern in ERROR_PATTERNS:
                if re.search(pattern, stripped, re.IGNORECASE):
                    error_lines.append(stripped)
                    break

            # Check for stack trace lines
            if re.match(STACK_TRACE_PATTERN, line) or re.match(PYTHON_TRACE_PATTERN, line):
                current_trace.append(stripped)
            elif current_trace:
                # Non-trace line after trace → include exception message
                if stripped.startswith(("java.", "javax.", "org.", "com.", "Caused by")):
                    current_trace.append(stripped)
                else:
                    stack_traces.append("\n".join(current_trace))
                    current_trace = []

            # Check for warning patterns
            for pattern in WARNING_PATTERNS:
                if re.search(pattern, stripped, re.IGNORECASE):
                    warnings.append(stripped)
                    break

        # Capture any remaining stack trace
        if current_trace:
            stack_traces.append("\n".join(current_trace))

        # Last 50 lines for context
        last_50 = "\n".join(lines[-50:]) if len(lines) >= 50 else raw_logs

        # Deduplicate while preserving order
        error_lines = list(dict.fromkeys(error_lines))
        warnings = list(dict.fromkeys(warnings))

        self.logger.info(
            f"Parsed: {len(error_lines)} errors, "
            f"{len(stack_traces)} traces, "
            f"{len(warnings)} warnings"
        )

        return ParsedLogs(
            error_lines=error_lines[:30],       # Cap at 30 to avoid huge prompts
            stack_traces=stack_traces[:10],      # Cap at 10
            warnings=warnings[:10],             # Cap at 10
            failed_stage=failed_stage,
            last_50_lines=last_50,
        )
