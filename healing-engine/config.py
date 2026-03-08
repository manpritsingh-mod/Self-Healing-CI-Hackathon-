"""
Self-Healing CI/CD Engine — Configuration
Loads environment variables and defines system constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Read and trim environment values to avoid hidden whitespace issues."""
    return os.getenv(name, default).strip()


# ── AI Provider ──────────────────────────────────────────────
AI_PROVIDER = _env("AI_PROVIDER", "ollama").lower()  # claude | ollama | openai | gemini
CLAUDE_API_KEY = _env("CLAUDE_API_KEY", "")
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-sonnet-4-20250514")
OLLAMA_URL = _env("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "llama3")
OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o")
GEMINI_API_KEY = _env("GEMINI_API_KEY", "")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")

# ── Jenkins ──────────────────────────────────────────────────
JENKINS_URL = _env("JENKINS_URL", "http://jenkins:8080")
JENKINS_USER = _env("JENKINS_USER", "admin")
JENKINS_TOKEN = _env("JENKINS_TOKEN", "")

# ── Slack ────────────────────────────────────────────────────
SLACK_WEBHOOK_URL = _env("SLACK_WEBHOOK_URL", "")
PUBLIC_ENGINE_URL = _env("PUBLIC_ENGINE_URL", "http://localhost:5000")
APPROVAL_SIGNING_SECRET = _env("APPROVAL_SIGNING_SECRET", "")

# ── GitHub Automation ──────────────────────────────────────────
GITHUB_TOKEN = _env("GITHUB_TOKEN", "")
GITHUB_OWNER = _env("GITHUB_OWNER", "")
GITHUB_REPO = _env("GITHUB_REPO", "")
GITHUB_BASE_BRANCH = _env("GITHUB_BASE_BRANCH", "master")

# ── Email (SMTP) ─────────────────────────────────────────────
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER", "")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")
NOTIFICATION_EMAIL = _env("NOTIFICATION_EMAIL", "")

# ── Engine Config ────────────────────────────────────────────
APP_PORT = int(os.getenv("APP_PORT", "5000"))
ENGINE_PORT = APP_PORT
ENGINE_HOST = _env("ENGINE_HOST", "0.0.0.0")
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "90"))
MAX_LOOPS = int(os.getenv("MAX_LOOPS", "3"))
TOKEN_DAILY_LIMIT = int(os.getenv("TOKEN_DAILY_LIMIT", "50000"))

# ── ChromaDB ─────────────────────────────────────────────────
CHROMA_PERSIST_DIR = _env("CHROMA_PERSIST_DIR", "/app/data/chroma")
CHROMA_COLLECTION = "healing_incidents"

# ── Constants (not configurable via .env) ────────────────────
VECTOR_MATCH_HIGH = CONFIDENCE_THRESHOLD / 100.0   # Above this → cached fix, skip LLM
VECTOR_MATCH_PARTIAL = 0.60   # Above this → include as LLM context
