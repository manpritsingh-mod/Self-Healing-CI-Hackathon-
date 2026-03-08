"""
Validator Agent — Tier 3 (LLM call #3+).
Critically reviews proposed fixes from Fix Agent.
Acts as the "second opinion" in the confidence loop.

Only approves if confidence >= 90%. Otherwise provides feedback
for Fix Agent to improve on the next loop.

Output: ValidatorResult(approved, feedback, confidence)
"""

from agents.base_agent import BaseAgent
from models.schemas import ValidatorResult, ErrorClass
from services.ai_service import ai_service
from core.prompt_builder import prompt_builder
from core.token_budget import token_budget


class ValidatorAgent(BaseAgent):
    """Reviews and validates proposed fixes. The strict gatekeeper."""

    def __init__(self):
        super().__init__(
            name="Validator",
            role="Validate proposed fixes with strict confidence scoring",
            uses_llm=True,
        )

    async def analyze(
        self,
        error_class: ErrorClass,
        root_cause: dict,
        proposed_fix: dict,
        error_lines: list[str],
        loop_number: int = 1,
    ) -> ValidatorResult:
        """
        Call LLM to validate a proposed fix.

        Args:
            error_class: Classified error type
            root_cause: Root cause analysis dict
            proposed_fix: Fix proposed by Fix Agent
            error_lines: Original error lines from logs
            loop_number: Current loop iteration (1-3)

        Returns:
            ValidatorResult with approved flag, feedback, and confidence score
        """
        estimated_tokens = 800
        if not token_budget.can_spend(estimated_tokens, ai_service.provider):
            self.logger.warning("Token budget exhausted. Auto-approving with low confidence.")
            return ValidatorResult(
                approved=False,
                feedback="Token budget exhausted — cannot validate",
                confidence=30,
            )

        self.logger.info(f"Validating fix (loop {loop_number})...")

        # Build dynamic prompt
        system_role, user_prompt = prompt_builder.build_validator_prompt(
            error_class=error_class,
            root_cause=root_cause,
            proposed_fix=proposed_fix,
            error_lines=error_lines,
        )

        # Call LLM with JSON hardening + retry
        response = await ai_service.ask_for_json(
            prompt=user_prompt,
            system_role=system_role,
            required_keys=["approved", "feedback", "confidence"],
            max_tokens=512,
            temperature=0.2,  # Low temp = strict, deterministic validation
            max_json_retries=2,
        )

        tokens_used = response.get("tokens_used", 0)
        token_budget.spend(tokens_used, response.get("provider", ""))

        if not response.get("success"):
            self.logger.error(f"LLM call failed for validation (loop {loop_number})")
            return ValidatorResult(
                approved=False,
                feedback="Validation failed — LLM unavailable",
                confidence=0,
            )

        # Structured response (or None after retry exhaustion)
        parsed = response.get("parsed")

        if parsed:
            confidence = ai_service._bounded_int(parsed.get("confidence", 0), default=0)
            approved_raw = str(parsed.get("approved", False)).lower()
            approved_flag = approved_raw in {"true", "1", "yes"}
            approved = approved_flag and confidence >= 90

            result = ValidatorResult(
                approved=approved,
                feedback=parsed.get("feedback") or "No feedback provided",
                confidence=confidence,
            )

            self.logger.info(
                f"Validation result: {'✅ APPROVED' if approved else '❌ REJECTED'} "
                f"(confidence: {confidence}%)"
            )

            return result
        self.logger.warning("Could not parse JSON from validator response after retries")
        fallback = ai_service.extract_validator_fallback(response.get("content", ""))
        if fallback:
            confidence = ai_service._bounded_int(fallback.get("confidence", 0), default=30)
            approved = bool(fallback.get("approved", False)) and confidence >= 90
            return ValidatorResult(
                approved=approved,
                feedback=fallback.get("feedback", "Fallback validator parse"),
                confidence=confidence,
            )

        return ValidatorResult(
            approved=False,
            feedback=response.get("content", "")[:300],
            confidence=30,
        )
