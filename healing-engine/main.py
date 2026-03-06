"""
main.py — FastAPI Application Entry Point
Self-Healing CI/CD Engine

Initializes services, mounts routes, and provides health/readiness checks.
"""

import sys
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add healing-engine to sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routes.webhook_routes import router as webhook_router
from routes.heal_routes import router as heal_router
from routes.config_routes import router as config_router
from services.vector_db_service import vector_db_service
from core.token_budget import token_budget
from config import ENGINE_PORT, ENGINE_HOST

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("healing-engine")


# ── Lifespan (startup/shutdown) ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    logger.info("═══ Self-Healing CI/CD Engine Starting ═══")

    # Initialize ChromaDB (vector store + incident memory)
    vector_db_service.initialize()
    logger.info(f"ChromaDB initialized. {vector_db_service.get_stats()['total_documents']} documents.")

    # Show budget status
    budget = token_budget.get_status()
    logger.info(f"Token budget: {budget['remaining']}/{budget['daily_limit']} remaining")

    logger.info("═══ Engine Ready ═══")
    yield

    # Shutdown
    logger.info("Shutting down services...")
    from services.ai_service import ai_service
    from services.slack_service import slack_service
    await ai_service.close()
    await slack_service.close()
    logger.info("═══ Engine Stopped ═══")


# ── FastAPI App ──
app = FastAPI(
    title="Self-Healing CI/CD Engine",
    description=(
        "AI-powered CI/CD healing engine with multi-agent architecture.\n\n"
        "**Pipeline**: Webhook → Detection → LogParser + GitDiff (parallel) → "
        "Classify → VectorDB Cache → RootCause (LLM) → "
        "ConfidenceLoop (Fix↔Validator) → Notify (Slack + Email)\n\n"
        "**Agents**: Detection, LogParser, GitDiff, RootCause, Fix, Validator, Notify\n\n"
        "**Key Feature**: Confidence Loop — two AI agents debate until ≥90% confidence"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──
app.include_router(webhook_router)
app.include_router(heal_router)
app.include_router(config_router)


# ── Health ──
@app.get("/health", tags=["System"])
async def health():
    """Health check — returns OK if engine is running."""
    return {
        "status": "healthy",
        "service": "self-healing-cicd-engine",
        "version": "1.0.0",
    }


@app.get("/ready", tags=["System"])
async def readiness():
    """Readiness check — verifies ChromaDB is accessible."""
    try:
        stats = vector_db_service.get_stats()
        budget = token_budget.get_status()
        return {
            "ready": True,
            "chroma_documents": stats["total_documents"],
            "tokens_remaining": budget["remaining"],
        }
    except Exception as e:
        return {"ready": False, "error": str(e)}


# ── Run ──
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=ENGINE_HOST,
        port=ENGINE_PORT,
        reload=True,
        log_level="info",
    )
