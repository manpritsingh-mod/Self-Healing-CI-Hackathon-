"""
Self-Healing CI/CD Engine — Configuration
Loads environment variables and defines system constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ── AI Provider ──────────────────────────────────────────────
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama")  # claude | ollama
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# ── Jenkins ──────────────────────────────────────────────────
JENKINS_URL = os.getenv("JENKINS_URL", "http://jenkins:8080")
JENKINS_USER = os.getenv("JENKINS_USER", "admin")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN", "")

# ── Slack ────────────────────────────────────────────────────
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# ── Email (SMTP) ─────────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")

# ── Engine Config ────────────────────────────────────────────
APP_PORT = int(os.getenv("APP_PORT", "5000"))
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "90"))
MAX_LOOPS = int(os.getenv("MAX_LOOPS", "3"))
TOKEN_DAILY_LIMIT = int(os.getenv("TOKEN_DAILY_LIMIT", "50000"))

# ── ChromaDB ─────────────────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "/app/data/chroma")
CHROMA_COLLECTION = "healing_incidents"

# ── Constants (not configurable via .env) ────────────────────
VECTOR_MATCH_HIGH = 0.85      # Above this → cached fix, skip LLM
VECTOR_MATCH_PARTIAL = 0.60   # Above this → include as LLM context
