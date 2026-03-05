"""
AI Service — Unified LLM Gateway
Routes all AI calls through a single interface.
Supports: Claude (primary) + Ollama (fallback).

Only 3 agents call this service:
  1. Root Cause Agent  (1 call)
  2. Fix Agent         (1-3 calls, looped)
  3. Validator Agent   (1-3 calls, looped)
"""

import httpx
import json
import logging
from typing import Optional
from config import (
    AI_PROVIDER, CLAUDE_API_KEY, CLAUDE_MODEL,
    OLLAMA_URL, OLLAMA_MODEL
)

logger = logging.getLogger(__name__)


class AIService:
    """Single gateway for all LLM calls. Handles provider switching and error fallback."""

    def __init__(self):
        self.provider = AI_PROVIDER
        self.total_tokens_used = 0
        self._client = httpx.AsyncClient(timeout=60.0)

    async def ask(
        self,
        prompt: str,
        system_role: str = "You are a CI/CD debugging expert.",
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> dict:
        """
        Send a prompt to the configured LLM provider.

        Returns:
            {
                "content": str,        # Raw LLM response text
                "tokens_used": int,    # Approximate token count
                "provider": str,       # "claude" or "ollama"
                "success": bool,
            }
        """
        try:
            if self.provider == "claude":
                return await self._ask_claude(prompt, system_role, max_tokens, temperature)
            else:
                return await self._ask_ollama(prompt, system_role, max_tokens, temperature)
        except Exception as e:
            logger.error(f"[AI] Primary provider '{self.provider}' failed: {e}")

            # Fallback: try the other provider
            if self.provider == "claude":
                logger.info("[AI] Falling back to Ollama...")
                try:
                    return await self._ask_ollama(prompt, system_role, max_tokens, temperature)
                except Exception as fallback_err:
                    logger.error(f"[AI] Ollama fallback also failed: {fallback_err}")
            else:
                logger.info("[AI] Falling back to Claude...")
                if CLAUDE_API_KEY:
                    try:
                        return await self._ask_claude(prompt, system_role, max_tokens, temperature)
                    except Exception as fallback_err:
                        logger.error(f"[AI] Claude fallback also failed: {fallback_err}")

            return {
                "content": "",
                "tokens_used": 0,
                "provider": "none",
                "success": False,
                "error": str(e),
            }

    async def _ask_claude(
        self, prompt: str, system_role: str, max_tokens: int, temperature: float
    ) -> dict:
        """Call Claude API (Anthropic)."""
        logger.info(f"[AI] Calling Claude ({CLAUDE_MODEL})...")

        response = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_role,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()

        content = data.get("content", [{}])[0].get("text", "")
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        self.total_tokens_used += tokens

        logger.info(f"[AI] Claude response: {tokens} tokens used")

        return {
            "content": content,
            "tokens_used": tokens,
            "provider": "claude",
            "success": True,
        }

    async def _ask_ollama(
        self, prompt: str, system_role: str, max_tokens: int, temperature: float
    ) -> dict:
        """Call Ollama local LLM."""
        logger.info(f"[AI] Calling Ollama ({OLLAMA_MODEL})...")

        response = await self._client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"{system_role}\n\n{prompt}",
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        content = data.get("response", "")
        # Ollama doesn't always return exact token counts
        tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
        if tokens == 0:
            tokens = len(prompt.split()) + len(content.split())  # rough estimate
        self.total_tokens_used += tokens

        logger.info(f"[AI] Ollama response: ~{tokens} tokens used")

        return {
            "content": content,
            "tokens_used": tokens,
            "provider": "ollama",
            "success": True,
        }

    def parse_json_response(self, raw_content: str) -> Optional[dict]:
        """
        Extract JSON from LLM response.
        Handles both clean JSON and markdown-wrapped JSON (```json ... ```).
        """
        text = raw_content.strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if "```" in text:
            try:
                json_block = text.split("```json")[-1].split("```")[0].strip()
                return json.loads(json_block)
            except (json.JSONDecodeError, IndexError):
                pass
            try:
                json_block = text.split("```")[-2].strip()
                return json.loads(json_block)
            except (json.JSONDecodeError, IndexError):
                pass

        # Try finding JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        logger.warning(f"[AI] Could not parse JSON from response: {text[:200]}...")
        return None

    async def close(self):
        """Clean up HTTP client."""
        await self._client.aclose()


# Singleton instance
ai_service = AIService()
