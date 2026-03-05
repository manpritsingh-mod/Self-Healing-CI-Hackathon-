"""
Token Budget Manager — 50K tokens/day guard.
Prevents overspending on LLM calls.

Tracks daily usage and provides:
  - can_spend(n): Check if budget allows n more tokens
  - spend(n): Record token usage
  - remaining(): Get remaining budget
  - Auto-reset at midnight
"""

import logging
from datetime import datetime, date
from config import TOKEN_DAILY_LIMIT

logger = logging.getLogger(__name__)


class TokenBudget:
    """Manages daily token spending with a hard ceiling."""

    def __init__(self, daily_limit: int = TOKEN_DAILY_LIMIT):
        self.daily_limit = daily_limit
        self._used_today = 0
        self._current_date = date.today()

    def _check_date_reset(self):
        """Reset counter if we've rolled past midnight."""
        today = date.today()
        if today != self._current_date:
            logger.info(
                f"[BUDGET] New day detected. Resetting budget. "
                f"Yesterday used: {self._used_today}/{self.daily_limit}"
            )
            self._used_today = 0
            self._current_date = today

    def can_spend(self, estimated_tokens: int) -> bool:
        """Check if there's enough budget for an estimated number of tokens."""
        self._check_date_reset()
        allowed = (self._used_today + estimated_tokens) <= self.daily_limit

        if not allowed:
            logger.warning(
                f"[BUDGET] Blocked! Used: {self._used_today}, "
                f"Requested: {estimated_tokens}, Limit: {self.daily_limit}"
            )

        return allowed

    def spend(self, tokens: int):
        """Record tokens spent."""
        self._check_date_reset()
        self._used_today += tokens
        remaining = self.daily_limit - self._used_today

        logger.info(
            f"[BUDGET] Spent {tokens} tokens. "
            f"Today: {self._used_today}/{self.daily_limit} "
            f"Remaining: {remaining}"
        )

        if remaining < 5000:
            logger.warning(f"[BUDGET] ⚠️ Low budget! Only {remaining} tokens remaining today.")

    @property
    def used_today(self) -> int:
        """Get tokens used today."""
        self._check_date_reset()
        return self._used_today

    @property
    def remaining(self) -> int:
        """Get remaining tokens for today."""
        self._check_date_reset()
        return max(0, self.daily_limit - self._used_today)

    def get_status(self) -> dict:
        """Get full budget status as a dict."""
        self._check_date_reset()
        return {
            "daily_limit": self.daily_limit,
            "used_today": self._used_today,
            "remaining": self.remaining,
            "date": str(self._current_date),
            "utilization_pct": round((self._used_today / self.daily_limit) * 100, 1),
        }


# Singleton instance
token_budget = TokenBudget()
