"""
Self-Healing CI/CD Engine — FastAPI Application Entry Point

This is the main application file that:
1. Creates the FastAPI app
2. Registers all route modules
3. Provides the /health endpoint
4. Configures logging

Run: uvicorn main:app --host 0.0.0.0 --port 5000 --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from config import APP_PORT, AI_PROVIDER, TOKEN_DAILY_LIMIT
from models.schemas import HealthResponse
from routes import webhook_routes, heal_routes, config_routes


# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("healing-engine")


# ── Lifespan (startup/shutdown) ──────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs on startup and shutdown."""
    logger.info("═" * 60)
    logger.info("  Self-Healing CI/CD Engine — Starting Up")
    logger.info(f"  AI Provider: {AI_PROVIDER}")
    logger.info(f"  Token Budget: {TOKEN_DAILY_LIMIT}/day")
    logger.info(f"  Port: {APP_PORT}")
    logger.info("═" * 60)

    # TODO: Day 3 — initialize ChromaDB client here
    # TODO: Day 2 — initialize AI service here

    yield

    logger.info("Self-Healing CI/CD Engine — Shutting Down")


# ── FastAPI App ──────────────────────────────────────────────
app = FastAPI(
    title="Self-Healing CI/CD Engine",
    description=(
        "Agentic AI system that automatically diagnoses and fixes "
        "CI/CD pipeline failures using 8 specialized agents, "
        "dynamic prompting, and a confidence-bounded fix/validator loop."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Jenkins plugin and browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Register Routes ──────────────────────────────────────────
app.include_router(webhook_routes.router)
app.include_router(heal_routes.router)
app.include_router(config_routes.router)


# ── Health Check ─────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """System health check — used by Docker, monitoring, and Jenkins plugin."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        ai_provider=AI_PROVIDER,
        token_budget_remaining=TOKEN_DAILY_LIMIT,  # TODO: wire to actual budget
    )


# ── Root ─────────────────────────────────────────────────────
@app.get("/", tags=["System"])
async def root():
    """Root endpoint — redirect info."""
    return {
        "message": "Self-Healing CI/CD Engine",
        "docs": "/docs",
        "health": "/health",
        "version": "1.0.0",
    }
