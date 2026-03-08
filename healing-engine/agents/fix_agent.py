"""
Fix Agent — Tier 3 (LLM call #2+).
Proposes a fix for the diagnosed root cause.
On subsequent loops, incorporates Validator feedback to improve the fix.

Output: FixResult(fix_description, fix_code, fix_steps)
"""

from agents.base_agent import BaseAgent
from models.schemas import FixResult, ErrorClass
from services.ai_service import ai_service
from core.prompt_builder import prompt_builder
from core.token_budget import token_budget


class FixAgent(BaseAgent):
    """Generates a fix for the diagnosed build failure using LLM."""

    def __init__(self):
        super().__init__(
            name="Fix",
            role="Generate code fixes for CI/CD failures via LLM",
            uses_llm=True,
        )

    async def analyze(
        self,
        error_class: ErrorClass,
        root_cause: dict,
        error_lines: list[str],
        validator_feedback: str = None,
        loop_number: int = 1,
    ) -> FixResult:
        """
        Call LLM to propose a fix.

        Args:
            error_class: Classified error type
            root_cause: Root cause analysis dict
            error_lines: Original error lines from logs
            validator_feedback: Feedback from Validator (loops 2+)
            loop_number: Current loop iteration (1-3)

        Returns:
            FixResult with fix description, code, and steps
        """
        estimated_tokens = 1200
        if not token_budget.can_spend(estimated_tokens, ai_service.provider):
            self.logger.warning("Token budget exhausted. Returning empty fix.")
            return FixResult(
                fix_description="Token budget exhausted — cannot generate fix",
                fix_code=None,
                fix_steps=["Contact team lead for manual resolution"],
            )

        if validator_feedback:
            self.logger.info(
                f"Loop {loop_number}: Incorporating validator feedback to improve fix"
            )

        # Build dynamic prompt (includes feedback on loops 2+)
        system_role, user_prompt = prompt_builder.build_fix_prompt(
            error_class=error_class,
            root_cause=root_cause,
            error_lines=error_lines,
            validator_feedback=validator_feedback,
        )

        # Call LLM with JSON hardening + retry
        response = await ai_service.ask_for_json(
            prompt=user_prompt,
            system_role=system_role,
            required_keys=["fix_description", "fix_code", "fix_steps", "confidence"],
            max_tokens=1024,
            temperature=0.4,  # Slightly more creative for fixes
            max_json_retries=2,
        )

        tokens_used = response.get("tokens_used", 0)
        token_budget.spend(tokens_used, response.get("provider", ""))

        if not response.get("success"):
            self.logger.error(f"LLM call failed for fix generation (loop {loop_number})")
            return FixResult(
                fix_description="LLM call failed — unable to generate fix",
                fix_steps=["Manually investigate the error"],
            )

        # Structured response (or None after retry exhaustion)
        parsed = response.get("parsed")

        if parsed:
            return FixResult(
                fix_description=parsed.get("fix_description") or "Fix generated",
                fix_code=parsed.get("fix_code"),
                fix_steps=parsed.get("fix_steps") or [],
                confidence=parsed.get("confidence") or 50,
            )
        else:
            self.logger.warning("Could not parse JSON from LLM, using raw text")
            return FixResult(
                fix_description=response["content"][:500],
                fix_code=None,
                fix_steps=["Review the suggested fix above"],
            )
