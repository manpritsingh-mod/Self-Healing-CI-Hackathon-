"""
Base Agent — Abstract base class for all 8 agents.
Each agent implements analyze() and has a name/role for logging and tracking.
"""

from abc import ABC, abstractmethod
from typing import Any
import logging
import time


class BaseAgent(ABC):
    """Abstract base for all healing agents."""

    def __init__(self, name: str, role: str, uses_llm: bool = False):
        self.name = name
        self.role = role
        self.uses_llm = uses_llm
        self.logger = logging.getLogger(f"agent.{name}")

    @abstractmethod
    async def analyze(self, *args, **kwargs) -> Any:
        """Core method every agent must implement."""
        pass

    async def run(self, *args, **kwargs) -> Any:
        """Wrapper that adds timing and logging around analyze()."""
        self.logger.info(f"[{self.name}] Starting... (LLM: {self.uses_llm})")
        start = time.time()

        try:
            result = await self.analyze(*args, **kwargs)
            elapsed = round(time.time() - start, 2)
            self.logger.info(f"[{self.name}] Done in {elapsed}s")
            return result
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            self.logger.error(f"[{self.name}] Failed after {elapsed}s: {e}")
            raise
