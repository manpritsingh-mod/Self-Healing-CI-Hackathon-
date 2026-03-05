"""
Self-Healing CI/CD Engine — Data Models
All Pydantic schemas for the healing pipeline.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime
import uuid


# ═══════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════

class ErrorClass(str, Enum):
    """Error classification categories (4 optimized + UNKNOWN fallback)."""
    COMPILATION = "COMPILATION"
    TEST_FAILURE = "TEST_FAILURE"
    DEPENDENCY = "DEPENDENCY"
    CONFIG = "CONFIG"
    UNKNOWN = "UNKNOWN"


class ResolutionMode(str, Enum):
    """How the incident was resolved."""
    READY_FIX = "READY_FIX"        # Confidence >= 90
    ESCALATION = "ESCALATION"      # Confidence < 90 after max loops
    CACHED = "CACHED"              # Vector DB cache hit


class Classification(str, Enum):
    """Whether the error matched a known class or not."""
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


# ═══════════════════════════════════════════════════════════
# Tier 1 Agent Outputs (no LLM)
# ═══════════════════════════════════════════════════════════

class ParsedLogs(BaseModel):
    """Output from Log Parser Agent — extracted error signals."""
    error_lines: List[str] = Field(default_factory=list, description="Lines containing errors")
    stack_traces: List[str] = Field(default_factory=list, description="Extracted stack traces")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    failed_stage: Optional[str] = Field(None, description="Jenkins stage that failed")
    last_50_lines: str = Field("", description="Last 50 lines of raw log for context")


class CommitData(BaseModel):
    """Output from Git Diff Agent — recent commit info."""
    commit_hash: Optional[str] = None
    author: Optional[str] = None
    message: Optional[str] = None
    files_changed: List[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# Tier 2 Agent Output (LLM)
# ═══════════════════════════════════════════════════════════

class RootCauseAnalysis(BaseModel):
    """Output from Root Cause Agent — diagnosis of the failure."""
    root_cause: str = ""
    error_category: ErrorClass = ErrorClass.UNKNOWN
    affected_file: Optional[str] = None
    affected_line: Optional[int] = None
    severity: str = "MEDIUM"           # HIGH | MEDIUM | LOW
    confidence: int = 0                # 0-100


# ═══════════════════════════════════════════════════════════
# Tier 3: Confidence Loop Models
# ═══════════════════════════════════════════════════════════

class LoopAttempt(BaseModel):
    """Single round in the Fix → Validator confidence loop."""
    loop_no: int
    fix_candidate: str
    validator_feedback: str
    confidence: int


class FixResult(BaseModel):
    """Output from Fix Agent — proposed fix."""
    fix_description: str = ""
    fix_code: Optional[str] = None
    fix_steps: List[str] = Field(default_factory=list)


class ValidatorResult(BaseModel):
    """Output from Validator Agent — fix evaluation."""
    approved: bool = False
    feedback: str = ""
    confidence: int = 0


# ═══════════════════════════════════════════════════════════
# Final Output — Incident
# ═══════════════════════════════════════════════════════════

class Incident(BaseModel):
    """Complete healing event — the final output of the pipeline."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    job_name: str = ""
    build_number: int = 0
    classification: Classification = Classification.UNKNOWN
    error_class: ErrorClass = ErrorClass.UNKNOWN
    root_cause: Optional[RootCauseAnalysis] = None
    loop_attempts: List[LoopAttempt] = Field(default_factory=list)
    final_fix: Optional[FixResult] = None
    final_confidence: int = 0
    resolution_mode: ResolutionMode = ResolutionMode.ESCALATION
    agents_used: List[str] = Field(default_factory=list)
    total_tokens_used: int = 0
    processing_time_seconds: float = 0.0


# ═══════════════════════════════════════════════════════════
# Slack Payload Contract
# ═══════════════════════════════════════════════════════════

class SlackPayload(BaseModel):
    """Structured Slack notification — confidence ALWAYS shown at end."""
    job_name: str
    build_number: int
    root_cause: str
    fix_description: str
    fix_code: Optional[str] = None
    mode: ResolutionMode
    manual_review_required: bool = False
    loop_count: int = 0
    agents_involved: List[str] = Field(default_factory=list)
    confidence: int                    # ALWAYS at the end of the message


# ═══════════════════════════════════════════════════════════
# API Request/Response Models
# ═══════════════════════════════════════════════════════════

class HealRequest(BaseModel):
    """POST /api/heal — request body from Jenkins plugin."""
    job_name: str
    build_number: int
    logs: Optional[str] = None         # Optional: override log fetching


class HealResponse(BaseModel):
    """POST /api/heal — immediate response with tracking ID."""
    healing_id: str
    status: str = "processing"


class WebhookPayload(BaseModel):
    """POST /webhook/jenkins — Jenkins webhook notification."""
    name: Optional[str] = None         # Job name
    url: Optional[str] = None          # Job URL
    build: Optional[dict] = None       # Build info (number, status, url, log)


class HealthResponse(BaseModel):
    """GET /health — system health check."""
    status: str = "healthy"
    version: str = "1.0.0"
    ai_provider: str = ""
    token_budget_remaining: int = 0
