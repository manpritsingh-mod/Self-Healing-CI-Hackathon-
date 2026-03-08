# Self-Healing CI/CD Engine 🔧

> AI-powered CI/CD pipeline failure detection, diagnosis, and automated fix generation.

## Architecture

```
Jenkins Webhook → Detection Agent → Orchestrator
  → Tier 1: LogParser + GitDiff (parallel, 0 tokens)
  → Classify: Hybrid weighted (stage hint + log evidence scoring)
  → VectorDB: ChromaDB cache (skip LLM if >85% match)
  → Tier 2: Root Cause Agent (LLM call #1)
  → Tier 3: Confidence Loop (Fix ↔ Validator, max 3 loops)
  → Notify: Slack + Email + ChromaDB incident memory
```

### Key Feature: Confidence Loop

Two AI agents **debate** every proposed fix:

1. **Fix Agent** generates solution
2. **Validator Agent** reviews it strictly
3. If confidence < 90% → Validator sends feedback, Fix Agent improves
4. Repeats up to 3× until ≥90% confidence or escalates

## 8 Agents

| Agent        | Tier | LLM | Role                                  |
| ------------ | ---- | --- | ------------------------------------- |
| Detection    | 0    | ❌  | Entry point — routes failures         |
| Log Parser   | 1    | ❌  | Regex extraction (25+ patterns)       |
| Git Diff     | 1    | ❌  | Commit context from Jenkins API       |
| Root Cause   | 2    | ✅  | Diagnoses failure via dynamic prompts |
| Fix          | 3    | ✅  | Generates code fixes                  |
| Validator    | 3    | ✅  | Reviews fixes (≥90% gatekeeper)       |
| Orchestrator | —    | ❌  | Coordinates entire pipeline           |
| Notify       | —    | ❌  | Slack + Email + ChromaDB storage      |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/manpritsingh-mod/Self-Healing-CI-Hackathon-.git
cd Self-Healing-CI-Hackathon-

# 2. Configure
cp .env.example .env
# Edit .env with your API keys

# 3. Run with Docker
docker-compose up -d

# 4. Verify
curl http://localhost:5000/health
open http://localhost:5000/docs
```

## API Endpoints

| Method | Endpoint                | Purpose                       |
| ------ | ----------------------- | ----------------------------- |
| GET    | `/health`               | Health check                  |
| GET    | `/ready`                | Readiness (ChromaDB + budget) |
| GET    | `/docs`                 | Swagger UI                    |
| POST   | `/webhook/jenkins`      | Jenkins webhook receiver      |
| POST   | `/api/heal`             | Trigger healing directly      |
| GET    | `/api/heal/{id}/status` | Check healing progress        |
| GET    | `/api/heal/{id}/result` | Get healing result            |
| GET    | `/api/tokens`           | Token usage today             |
| GET    | `/api/config`           | Engine configuration          |
| GET    | `/api/incidents`        | Incident history              |
| GET    | `/api/incidents/{id}`   | Incident detail               |
| GET    | `/api/stats`            | System statistics             |

## Tech Stack

- **Backend**: FastAPI + Python 3.11
- **AI**: Claude API (primary) + Ollama (fallback)
- **Vector DB**: ChromaDB (similarity search + incident memory)
- **Notifications**: Slack webhooks + SMTP email
- **CI/CD**: Jenkins pipelines
- **Infrastructure**: Docker Compose

## Project Structure

```
self-healing-cicd/
├── docker-compose.yml
├── .env.example
├── healing-engine/
│   ├── main.py              # FastAPI app entry
│   ├── config.py            # Environment loader
│   ├── agents/
│   │   ├── base_agent.py          # Abstract base
│   │   ├── detection_agent.py     # Tier 0: entry point
│   │   ├── log_parser_agent.py    # Tier 1: regex parser
│   │   ├── git_diff_agent.py      # Tier 1: commit context
│   │   ├── root_cause_agent.py    # Tier 2: LLM diagnosis
│   │   ├── fix_agent.py           # Tier 3: LLM fix gen
│   │   ├── validator_agent.py     # Tier 3: LLM validator
│   │   ├── orchestrator_agent.py  # Pipeline coordinator
│   │   └── notify_agent.py        # Slack + Email + DB
│   ├── core/
│   │   ├── token_budget.py        # 50K/day guard
│   │   ├── prompt_builder.py      # Dynamic prompt assembly
│   │   └── confidence_loop.py     # Fix↔Validator debate
│   ├── services/
│   │   ├── ai_service.py          # Claude + Ollama gateway
│   │   ├── jenkins_service.py     # Jenkins REST client
│   │   ├── vector_db_service.py   # ChromaDB wrapper
│   │   ├── slack_service.py       # Slack notifications
│   │   └── email_service.py       # Email notifications
│   ├── models/
│   │   └── schemas.py             # Pydantic models
│   └── routes/
│       ├── webhook_routes.py
│       ├── heal_routes.py
│       └── config_routes.py
└── jenkins-config/
    ├── Dockerfile
    ├── plugins.txt
    └── jobs/
        ├── Jenkinsfile-success
        ├── Jenkinsfile-compile-error
        ├── Jenkinsfile-test-failure
        ├── Jenkinsfile-dependency-err
        └── Jenkinsfile-config-error
```
