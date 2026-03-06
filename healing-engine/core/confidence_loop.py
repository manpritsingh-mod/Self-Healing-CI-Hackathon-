"""
Confidence Loop — The Fix ↔ Validator debate engine.
Runs up to MAX_LOOPS iterations of Fix → Validate until confidence >= 90%.

Two possible outcomes:
  1. READY_FIX:  confidence >= 90% → ready to share
  2. ESCALATION: confidence < 90% after max loops → escalate with best attempt
"""

import logging
from models.schemas import (
    ErrorClass, FixResult, ValidatorResult,
    LoopAttempt, ResolutionMode,
)
from agents.fix_agent import FixAgent
from agents.validator_agent import ValidatorAgent
from config import CONFIDENCE_THRESHOLD, MAX_LOOPS

logger = logging.getLogger(__name__)


class ConfidenceLoop:
    """Runs the Fix → Validate debate loop until confidence threshold is met."""

    def __init__(self):
        self.fix_agent = FixAgent()
        self.validator_agent = ValidatorAgent()

    async def run(
        self,
        error_class: ErrorClass,
        root_cause: dict,
        error_lines: list[str],
    ) -> tuple[FixResult, list[LoopAttempt], int, ResolutionMode]:
        """
        Execute the confidence loop.

        Args:
            error_class: Classified error type
            root_cause: Root cause analysis dict
            error_lines: Original error lines

        Returns:
            (final_fix, loop_attempts, final_confidence, resolution_mode)
        """
        logger.info(
            f"[LOOP] Starting confidence loop "
            f"(threshold: {CONFIDENCE_THRESHOLD}%, max loops: {MAX_LOOPS})"
        )

        attempts: list[LoopAttempt] = []
        best_fix = None
        best_confidence = 0
        validator_feedback = None

        for loop_no in range(1, MAX_LOOPS + 1):
            logger.info(f"[LOOP] ═══ Iteration {loop_no}/{MAX_LOOPS} ═══")

            # ── Fix Agent generates/improves fix ──
            fix_result = await self.fix_agent.run(
                error_class=error_class,
                root_cause=root_cause,
                error_lines=error_lines,
                validator_feedback=validator_feedback,
                loop_number=loop_no,
            )

            # ── Validator Agent reviews the fix ──
            fix_dict = {
                "fix_description": fix_result.fix_description,
                "fix_code": fix_result.fix_code,
                "fix_steps": fix_result.fix_steps,
            }

            validator_result = await self.validator_agent.run(
                error_class=error_class,
                root_cause=root_cause,
                proposed_fix=fix_dict,
                error_lines=error_lines,
                loop_number=loop_no,
            )

            # ── Record attempt ──
            attempt = LoopAttempt(
                loop_no=loop_no,
                fix_candidate=fix_result.fix_description,
                validator_feedback=validator_result.feedback,
                confidence=validator_result.confidence,
            )
            attempts.append(attempt)

            # Track best
            if validator_result.confidence > best_confidence:
                best_confidence = validator_result.confidence
                best_fix = fix_result

            logger.info(
                f"[LOOP] Loop {loop_no} result: "
                f"confidence={validator_result.confidence}% "
                f"(best so far: {best_confidence}%)"
            )

            # ── Check threshold ──
            if validator_result.confidence >= CONFIDENCE_THRESHOLD:
                logger.info(
                    f"[LOOP] ✅ READY FIX — confidence {validator_result.confidence}% "
                    f"meets threshold {CONFIDENCE_THRESHOLD}%"
                )
                return (
                    fix_result,
                    attempts,
                    validator_result.confidence,
                    ResolutionMode.READY_FIX,
                )

            # ── Prepare feedback for next loop ──
            validator_feedback = validator_result.feedback
            logger.info(f"[LOOP] Fix rejected. Passing feedback to Fix Agent for next iteration.")

        # ── Max loops exhausted ──
        logger.warning(
            f"[LOOP] ⚠️ ESCALATION — max loops ({MAX_LOOPS}) reached. "
            f"Best confidence: {best_confidence}%"
        )

        return (
            best_fix or FixResult(fix_description="No viable fix found"),
            attempts,
            best_confidence,
            ResolutionMode.ESCALATION,
        )
