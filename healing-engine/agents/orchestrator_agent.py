"""
Orchestrator Agent — The brain of the healing engine.
Coordinates the entire pipeline:

  1. Intake (from Detection Agent or API)
  2. Tier 1: Log Parser + Git Diff (parallel, no LLM)
  3. Classify error (hybrid: stage hint + log evidence scoring)
  4. Vector DB search (before LLM)
  5. Tier 2: Root Cause Agent (LLM call #1)
  6. Tier 3: Confidence Loop — Fix ↔ Validator (LLM calls #2-7)
  7. Build Incident + Notify

Includes the ErrorClassifier (hybrid weighted scoring).
"""

import re
import asyncio
import time
import logging
from collections import Counter
from typing import Optional

from agents.base_agent import BaseAgent
from agents.log_parser_agent import LogParserAgent
from agents.git_diff_agent import GitDiffAgent
from agents.root_cause_agent import RootCauseAgent
from core.confidence_loop import ConfidenceLoop
from agents.notify_agent import NotifyAgent
from services.jenkins_service import jenkins_service
from services.vector_db_service import vector_db_service
from core.token_budget import token_budget
from models.schemas import (
    Incident, Classification, ErrorClass, ResolutionMode,
    ParsedLogs, CommitData,
)
from config import VECTOR_MATCH_HIGH, VECTOR_MATCH_PARTIAL

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Hybrid Weighted Error Classifier
# ═══════════════════════════════════════════════════════════

class ErrorClassifier:
    """Hybrid classification: stage name hint + log content weighted scoring.

    Why hybrid?
    - Stage name alone is unreliable (teams name stages differently)
    - Log regex alone can be ambiguous (same text matches multiple classes)
    - Hybrid: stage gives a fast hint, log scoring gives ground truth
    - Log evidence ALWAYS overrides stage hint when there is a match
    - If neither matches → UNKNOWN (still fully processed)
    """

    STAGE_HINTS = {
        r"(?i)(build|compile|maven|gradle|javac|gcc|make)": ErrorClass.COMPILATION,
        r"(?i)(test|junit|pytest|spec|mocha|jest|surefire)": ErrorClass.TEST_FAILURE,
        r"(?i)(install|dep|resolve|download|npm|pip|restore)": ErrorClass.DEPENDENCY,
        r"(?i)(config|env|setup|init|provision)": ErrorClass.CONFIG,
    }

    LOG_EVIDENCE = {
        ErrorClass.COMPILATION: [
            r"cannot find symbol",
            r"error:.*expected",
            r"syntax error",
            r"incompatible types",
            r"compilation.*fail",
            r"undefined reference",
            r"does not exist",
            r"cannot resolve",
            r"non-static method",
        ],
        ErrorClass.TEST_FAILURE: [
            r"Tests run:.*Failures: [1-9]",
            r"Assertion.*Error",
            r"FAILED.*test",
            r"Expected.*but.*was",
            r"AssertEquals",
            r"assert.*failed",
            r"test.*FAIL",
        ],
        ErrorClass.DEPENDENCY: [
            r"Could not resolve",
            r"404 Not Found",
            r"npm ERR!",
            r"ModuleNotFoundError",
            r"No matching version",
            r"dependency.*not found",
            r"package.*unavailable",
            r"SNAPSHOT.*not found",
        ],
        ErrorClass.CONFIG: [
            r"FileNotFoundException.*(?:config|properties|yaml|yml)",
            r"environment variable.*not set",
            r"YAML.*error",
            r"permission denied",
            r"connection refused",
            r"No such file",
            r"missing.*configuration",
        ],
    }

    def classify(self, failed_stage: Optional[str], error_lines: list[str]) -> ErrorClass:
        """Classify error: log evidence wins over stage hint."""
        # Step 1: Score via log content (GROUND TRUTH)
        scores = Counter()
        log_text = "\n".join(error_lines)

        for error_class, patterns in self.LOG_EVIDENCE.items():
            for pattern in patterns:
                matches = re.findall(pattern, log_text, re.IGNORECASE)
                scores[error_class] += len(matches)

        if scores and scores.most_common(1)[0][1] > 0:
            winner = scores.most_common(1)[0][0]
            logger.info(f"[CLASSIFY] Log evidence → {winner.value} (score: {scores[winner]})")
            return winner

        # Step 2: Fallback to stage hint
        if failed_stage:
            for pattern, error_class in self.STAGE_HINTS.items():
                if re.search(pattern, failed_stage):
                    logger.info(f"[CLASSIFY] Stage hint → {error_class.value} (stage: '{failed_stage}')")
                    return error_class

        logger.info("[CLASSIFY] No match → UNKNOWN")
        return ErrorClass.UNKNOWN


# ═══════════════════════════════════════════════════════════
# Orchestrator Agent
# ═══════════════════════════════════════════════════════════

class OrchestratorAgent(BaseAgent):
    """Coordinates the full healing pipeline end-to-end."""

    def __init__(self):
        super().__init__(
            name="Orchestrator",
            role="Coordinate healing pipeline across all agents",
            uses_llm=False,
        )
        self.classifier = ErrorClassifier()
        self.log_parser = LogParserAgent()
        self.git_diff = GitDiffAgent()
        self.root_cause_agent = RootCauseAgent()
        self.confidence_loop = ConfidenceLoop()
        self.notify_agent = NotifyAgent()

    async def analyze(
        self,
        job_name: str,
        build_number: int,
        raw_logs: str = None,
    ) -> Incident:
        """
        Run the full healing pipeline.

        Args:
            job_name: Jenkins job name
            build_number: Build number
            raw_logs: Optional raw logs (if not provided, fetched from Jenkins)

        Returns:
            Complete Incident with root cause, fix, confidence, mode
        """
        start_time = time.time()
        agents_used = []

        logger.info(f"[ORCHESTRATOR] ═══ Starting: {job_name} #{build_number} ═══")

        # ── Step 1: Fetch logs if not provided ──
        if not raw_logs:
            logger.info("[ORCHESTRATOR] Fetching logs from Jenkins...")
            raw_logs = await jenkins_service.get_build_logs(job_name, build_number)

        if not raw_logs:
            logger.error("[ORCHESTRATOR] No logs available. Cannot proceed.")
            return Incident(
                job_name=job_name,
                build_number=build_number,
                resolution_mode=ResolutionMode.ESCALATION,
            )

        # ── Step 2: Tier 1 — Parallel data gathering (no LLM) ──
        logger.info("[ORCHESTRATOR] Tier 1: Log Parser + Git Diff (parallel)")

        failed_stage = await jenkins_service.get_failed_stage(job_name, build_number)
        agents_used.append("LogParser")
        agents_used.append("GitDiff")

        parsed_logs, git_diff = await asyncio.gather(
            self.log_parser.run(raw_logs, failed_stage),
            self.git_diff.run(job_name, build_number),
        )

        # ── Step 3: Classify error (hybrid: stage + log evidence) ──
        error_class = self.classifier.classify(failed_stage, parsed_logs.error_lines)
        classification = Classification.KNOWN if error_class != ErrorClass.UNKNOWN else Classification.UNKNOWN

        logger.info(f"[ORCHESTRATOR] Classification: {classification.value} → {error_class.value}")

        # ── Step 4: Vector DB search (before LLM) ──
        logger.info("[ORCHESTRATOR] Searching Vector DB for similar past errors...")
        vector_matches = await vector_db_service.search(parsed_logs.error_lines)

        if vector_matches and vector_matches[0]["similarity"] > VECTOR_MATCH_HIGH:
            # Cache hit — skip LLM entirely
            cached = vector_matches[0]
            logger.info(
                f"[ORCHESTRATOR] ✅ Cache HIT (similarity: {cached['similarity']}). "
                f"Skipping LLM."
            )
            elapsed = round(time.time() - start_time, 2)
            agents_used.append("VectorDB-Cache")

            return Incident(
                job_name=job_name,
                build_number=build_number,
                classification=classification,
                error_class=error_class,
                final_fix=None,  # cached fix in metadata
                final_confidence=int(cached["similarity"] * 100),
                resolution_mode=ResolutionMode.CACHED,
                agents_used=agents_used,
                total_tokens_used=0,
                processing_time_seconds=elapsed,
            )

        # Include partial matches as context
        vector_context = [
            m for m in vector_matches
            if m["similarity"] > VECTOR_MATCH_PARTIAL
        ] if vector_matches else None

        # ── Step 5: Tier 2 — Root Cause Agent (LLM call #1) ──
        logger.info("[ORCHESTRATOR] Tier 2: Root Cause Agent (LLM)")
        agents_used.append("RootCause")

        root_cause_result = await self.root_cause_agent.run(
            error_class=error_class,
            parsed_logs=parsed_logs,
            git_diff=git_diff,
            vector_context=vector_context,
        )

        root_cause_dict = {
            "root_cause": root_cause_result.root_cause,
            "error_category": root_cause_result.error_category.value,
            "affected_file": root_cause_result.affected_file,
            "affected_line": root_cause_result.affected_line,
            "severity": root_cause_result.severity,
        }

        # ── Step 6: Tier 3 — Confidence Loop (Fix ↔ Validator) ──
        logger.info("[ORCHESTRATOR] Tier 3: Confidence Loop (Fix ↔ Validator)")
        agents_used.extend(["Fix", "Validator"])

        fix_result, loop_attempts, final_confidence, resolution_mode = \
            await self.confidence_loop.run(
                error_class=error_class,
                root_cause=root_cause_dict,
                error_lines=parsed_logs.error_lines,
            )

        # ── Step 7: Build Incident ──
        elapsed = round(time.time() - start_time, 2)
        tokens_total = token_budget.used_today  # Approximate for this run

        incident = Incident(
            job_name=job_name,
            build_number=build_number,
            classification=classification,
            error_class=error_class,
            root_cause=root_cause_result,
            loop_attempts=loop_attempts,
            final_fix=fix_result,
            final_confidence=final_confidence,
            resolution_mode=resolution_mode,
            agents_used=agents_used,
            total_tokens_used=tokens_total,
            processing_time_seconds=elapsed,
        )

        # ── Step 8: Notify (Slack + Email + Chroma metadata) ──
        logger.info("[ORCHESTRATOR] Step 8: Notify Agent")
        agents_used.append("Notify")
        await self.notify_agent.run(incident)

        logger.info(
            f"[ORCHESTRATOR] ═══ Complete: {resolution_mode.value} ═══\n"
            f"  Confidence: {final_confidence}%\n"
            f"  Loops: {len(loop_attempts)}\n"
            f"  Time: {elapsed}s\n"
            f"  Agents: {', '.join(agents_used)}"
        )

        return incident
