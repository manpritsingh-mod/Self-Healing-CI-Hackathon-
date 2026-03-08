"""
AI Service — Unified LLM Gateway
Routes all AI calls through a single interface.
Supports: Claude, OpenAI, Gemini, and Ollama (fallback for all).

Only 3 agents call this service:
  1. Root Cause Agent  (1 call)
  2. Fix Agent         (1-3 calls, looped)
  3. Validator Agent   (1-3 calls, looped)
"""

import httpx
import json
import logging
import re
from typing import Any, Optional
from config import (
    AI_PROVIDER, CLAUDE_API_KEY, CLAUDE_MODEL,
    OLLAMA_URL, OLLAMA_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL
)

logger = logging.getLogger(__name__)


class AIService:
    """Single gateway for all LLM calls. Handles provider switching and error fallback."""

    def __init__(self):
        self.provider = AI_PROVIDER
        self.total_tokens_used = 0
        self._client = httpx.AsyncClient(timeout=900.0)
        
        # Initialize Gemini if available
        if GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel(GEMINI_MODEL)
            except ImportError:
                logger.warning("[AI] google-generativeai not installed, Gemini disabled")
                self.gemini_model = None
        else:
            self.gemini_model = None

    async def ask(
        self,
        prompt: str,
        system_role: str = "You are a CI/CD debugging expert.",
        max_tokens: int = 1024,
        temperature: float = 0.3,
        force_json: bool = False,
    ) -> dict:
        """
        Send a prompt to the configured LLM provider.
        Automatically falls back to other configured providers if one fails.
        """
        # Determine strict priority of available providers
        providers_to_try = [self.provider]
        
        # Add other cloud providers if API keys are present
        if OPENAI_API_KEY and "openai" not in providers_to_try:
            providers_to_try.append("openai")
        if GEMINI_API_KEY and "gemini" not in providers_to_try:
            providers_to_try.append("gemini")
        if CLAUDE_API_KEY and "claude" not in providers_to_try:
            providers_to_try.append("claude")
            
        # Always append local Ollama as the absolute last resort
        if "ollama" not in providers_to_try:
            providers_to_try.append("ollama")

        last_error = "No providers available"

        for p in providers_to_try:
            try:
                if p == "claude":
                    return await self._ask_claude(
                        prompt, system_role, max_tokens, temperature, force_json=force_json
                    )
                elif p == "openai":
                    return await self._ask_openai(
                        prompt, system_role, max_tokens, temperature, force_json=force_json
                    )
                elif p == "gemini":
                    return await self._ask_gemini(
                        prompt, system_role, max_tokens, temperature, force_json=force_json
                    )
                elif p == "ollama":
                    return await self._ask_ollama(
                        prompt, system_role, max_tokens, temperature, force_json=force_json
                    )
            except Exception as e:
                logger.error(f"[AI] Provider '{p}' failed: {e}")
                last_error = str(e)
                logger.info(f"[AI] Trying next fallback provider...")
                continue # Try the next one

        logger.error("[AI] ALL available AI providers failed.")
        return {
            "content": "",
            "tokens_used": 0,
            "provider": "none",
            "success": False,
            "error": last_error,
        }

    async def _ask_claude(
        self, prompt: str, system_role: str, max_tokens: int, temperature: float, force_json: bool = False
    ) -> dict:
        """Call Claude API (Anthropic)."""
        if not CLAUDE_API_KEY:
            raise ValueError("CLAUDE_API_KEY not configured")
            
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

    async def _ask_openai(
        self, prompt: str, system_role: str, max_tokens: int, temperature: float, force_json: bool = False
    ) -> dict:
        """Call OpenAI API."""
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not configured")
            
        logger.info(f"[AI] Calling OpenAI ({OPENAI_MODEL})...")

        payload = {
            "model": OPENAI_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt}
            ],
        }
        if force_json:
            payload["response_format"] = {"type": "json_object"}

        response = await self._client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        self.total_tokens_used += tokens

        logger.info(f"[AI] OpenAI response: {tokens} tokens used")

        return {
            "content": content,
            "tokens_used": tokens,
            "provider": "openai",
            "success": True,
        }

    async def _ask_gemini(
        self, prompt: str, system_role: str, max_tokens: int, temperature: float, force_json: bool = False
    ) -> dict:
        """Call Google Gemini API."""
        if not self.gemini_model:
            raise ValueError("Gemini model not initialized (missing API key or module)")
            
        logger.info(f"[AI] Calling Gemini ({GEMINI_MODEL})...")

        try:
            import google.generativeai as genai
            
            # Combine system role and prompt since Gemini expects it 
            # as a single instruction set for standard chat completions
            full_prompt = f"SYSTEM INSTRUCTION: {system_role}\n\nUSER PROMPT:\n{prompt}"
            
            generation_config = genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            if force_json:
                generation_config.response_mime_type = "application/json"

            response = await self.gemini_model.generate_content_async(
                full_prompt,
                generation_config=generation_config
            )
            
            content = response.text
            
            # Rough token estimate if proper usage isn't nested right
            try:
                tokens = response.usage_metadata.total_token_count
            except AttributeError:
                tokens = len(full_prompt.split()) + len(content.split())
                
            self.total_tokens_used += tokens
            logger.info(f"[AI] Gemini response: ~{tokens} tokens used")

            return {
                "content": content,
                "tokens_used": tokens,
                "provider": "gemini",
                "success": True,
            }
        except Exception as e:
            logger.error(f"[AI] Gemini error details: {e}")
            raise

    async def _ask_ollama(
        self, prompt: str, system_role: str, max_tokens: int, temperature: float, force_json: bool = False
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

    async def ask_for_json(
        self,
        prompt: str,
        system_role: str,
        required_keys: list[str],
        max_tokens: int = 1024,
        temperature: float = 0.3,
        max_json_retries: int = 2,
    ) -> dict:
        """
        Ask model for strict JSON. If parsing fails, retry with a JSON-repair prompt.
        """
        json_rules = (
            "\n\nCRITICAL OUTPUT RULES:\n"
            "- Return exactly ONE JSON object.\n"
            "- No markdown fences.\n"
            "- No extra text before or after the JSON.\n"
            "- Use double quotes for keys and string values.\n"
            "- Include all required keys."
        )

        total_tokens = 0
        last_provider = ""
        last_content = ""
        next_prompt = prompt + json_rules
        next_system_role = system_role
        next_temperature = temperature
        next_max_tokens = max_tokens

        for attempt in range(1, max_json_retries + 2):
            response = await self.ask(
                prompt=next_prompt,
                system_role=next_system_role,
                max_tokens=next_max_tokens,
                temperature=next_temperature,
                force_json=True,
            )

            total_tokens += response.get("tokens_used", 0)
            last_provider = response.get("provider", last_provider)
            last_content = response.get("content", "")

            if not response.get("success"):
                return {
                    "success": False,
                    "parsed": None,
                    "content": last_content,
                    "provider": last_provider,
                    "tokens_used": total_tokens,
                    "attempts": attempt,
                }

            parsed = self.parse_json_response(last_content)
            if isinstance(parsed, dict):
                missing_keys = [k for k in required_keys if k not in parsed]
                if not missing_keys:
                    return {
                        "success": True,
                        "parsed": parsed,
                        "content": last_content,
                        "provider": last_provider,
                        "tokens_used": total_tokens,
                        "attempts": attempt,
                    }

                logger.warning(
                    f"[AI] JSON parsed but missing keys {missing_keys} (attempt {attempt})."
                )

            if attempt <= max_json_retries:
                next_prompt = self._build_json_repair_prompt(last_content, required_keys)
                next_system_role = "You convert malformed model output into strict valid JSON."
                next_temperature = 0.0
                next_max_tokens = min(max_tokens, 512)

        return {
            "success": True,
            "parsed": None,
            "content": last_content,
            "provider": last_provider,
            "tokens_used": total_tokens,
            "attempts": max_json_retries + 1,
        }

    def parse_json_response(self, raw_content: str) -> Optional[dict]:
        """
        Extract JSON from LLM response.
        Handles clean JSON, markdown-wrapped JSON, and common malformed JSON patterns.
        """
        if not raw_content:
            return None

        text = raw_content.strip().replace("\ufeff", "")
        candidates: list[str] = [text]
        candidates.extend(self._extract_code_fence_candidates(text))

        balanced_json = self._extract_balanced_json_object(text)
        if balanced_json:
            candidates.append(balanced_json)

        seen = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)

            parsed = self._try_parse_json_candidate(candidate)
            if isinstance(parsed, dict):
                return parsed

        logger.warning(f"[AI] Could not parse JSON from response: {text[:200]}...")
        return None

    def extract_validator_fallback(self, raw_content: str) -> Optional[dict]:
        """
        Best-effort fallback when validator JSON is malformed.
        """
        if not raw_content:
            return None

        text = raw_content.strip()
        approved = False
        confidence = None

        approved_match = re.search(
            r"approved\s*[:=]\s*(true|false|yes|no|approved|rejected)",
            text,
            flags=re.IGNORECASE,
        )
        if approved_match:
            approved_val = approved_match.group(1).lower()
            approved = approved_val in {"true", "yes", "approved"}
        elif re.search(r"\bapprove(d)?\b", text, flags=re.IGNORECASE):
            approved = not re.search(r"\b(not|reject|rejected)\b", text, flags=re.IGNORECASE)

        confidence_match = re.search(r"confidence\s*[:=]?\s*(\d{1,3})", text, flags=re.IGNORECASE)
        if not confidence_match:
            confidence_match = re.search(r"\b(\d{1,3})\s*%", text)
        if confidence_match:
            confidence = self._bounded_int(confidence_match.group(1), default=0)

        if confidence is None:
            return None

        feedback = text
        if len(feedback) > 800:
            feedback = feedback[:800]

        return {
            "approved": approved,
            "confidence": confidence,
            "feedback": feedback,
        }

    @staticmethod
    def _bounded_int(value: Any, default: int = 0, min_value: int = 0, max_value: int = 100) -> int:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _build_json_repair_prompt(previous_output: str, required_keys: list[str]) -> str:
        keys_block = ", ".join(required_keys)
        return (
            "The text below is intended to be JSON but is malformed or missing fields.\n"
            "Convert it into ONE strict JSON object only.\n"
            f"Required keys: {keys_block}\n"
            "Rules:\n"
            "- No markdown fences\n"
            "- No commentary\n"
            "- Double quotes only\n"
            "- Valid JSON syntax\n\n"
            "TEXT TO CONVERT:\n"
            f"{previous_output}"
        )

    @staticmethod
    def _extract_code_fence_candidates(text: str) -> list[str]:
        return [match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text)]

    @staticmethod
    def _extract_balanced_json_object(text: str) -> Optional[str]:
        start_idx = None
        depth = 0
        in_string = False
        escape = False

        for idx, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == "\"":
                    in_string = False
                continue

            if ch == "\"":
                in_string = True
                continue

            if ch == "{":
                if depth == 0:
                    start_idx = idx
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_idx is not None:
                        return text[start_idx:idx + 1]

        return None

    def _try_parse_json_candidate(self, candidate: str) -> Optional[dict]:
        candidate = candidate.strip()
        if not candidate:
            return None

        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        cleaned = self._cleanup_common_json_issues(candidate)
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _cleanup_common_json_issues(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^\s*json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("“", "\"").replace("”", "\"").replace("’", "'")
        cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)
        cleaned = re.sub(r"(?m)^\s*//.*$", "", cleaned)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        cleaned = re.sub(r"\bTrue\b", "true", cleaned)
        cleaned = re.sub(r"\bFalse\b", "false", cleaned)
        cleaned = re.sub(r"\bNone\b", "null", cleaned)

        if "'" in cleaned and "\"" not in cleaned:
            cleaned = cleaned.replace("'", "\"")

        return cleaned

    async def close(self):
        """Clean up HTTP client."""
        await self._client.aclose()


# Singleton instance
ai_service = AIService()
