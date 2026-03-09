✅ System Check Endpoints (GET — no body needed)
#	URL	Purpose
1	GET http://localhost:5000/health	Basic health check
2	GET http://localhost:5000/ready	Readiness + ChromaDB status
3	GET http://localhost:5000/api/config	Engine configuration
4	GET http://localhost:5000/api/tokens	Daily token usage
5	GET http://localhost:5000/api/stats	Vector DB + system stats
6	GET http://localhost:5000/api/incidents	All past incidents
✅ Core Webhook (POST — requires JSON body)
#	URL	Purpose
7	POST http://localhost:5000/webhook/jenkins	Trigger healing pipeline
Start with GET http://localhost:5000/health — if that returns {"status": "healthy"}, your engine is alive and you can test the rest!


__________________________________________________________________________________________________________


# 🧪 Self-Healing CI/CD Engine — Postman API Testing Guide

> **Base URL**: `http://localhost:5000`
> **Headers for all POST requests**: `Content-Type: application/json`

---

## Phase 1: Health & System Verification

Start here. If these fail, nothing else will work.

### 1.1 Health Check

| Field  | Value                          |
| ------ | ------------------------------ |
| Method | `GET`                          |
| URL    | `http://localhost:5000/health` |
| Body   | None                           |

**Expected Response** (`200 OK`):

```json
{
  "status": "healthy",
  "service": "self-healing-cicd-engine",
  "version": "1.0.0"
}
```

---

### 1.2 Readiness Check (ChromaDB + Token Budget)

| Field  | Value                         |
| ------ | ----------------------------- |
| Method | `GET`                         |
| URL    | `http://localhost:5000/ready` |
| Body   | None                          |

**Expected Response** (`200 OK`):

```json
{
  "ready": true,
  "chroma_documents": 0,
  "tokens_remaining": 50000
}
```

> [!TIP]
> If `ready` is `false`, ChromaDB failed to initialize. Check Docker logs.

---

## Phase 2: Configuration & Monitoring APIs

### 2.1 Engine Configuration

| Field  | Value                              |
| ------ | ---------------------------------- |
| Method | `GET`                              |
| URL    | `http://localhost:5000/api/config` |
| Body   | None                               |

**Expected Response**:

```json
{
  "ai_provider": "gemini",
  "confidence_threshold": 90,
  "max_loops": 3,
  "token_daily_limit": 0
}
```

---

### 2.2 Token Usage

| Field  | Value                              |
| ------ | ---------------------------------- |
| Method | `GET`                              |
| URL    | `http://localhost:5000/api/tokens` |
| Body   | None                               |

**Expected Response**:

```json
{
  "used_today": 0,
  "daily_limit": 0,
  "remaining": 0,
  "percentage_used": 0
}
```

---

### 2.3 System Stats (Vector DB + Tokens)

| Field  | Value                             |
| ------ | --------------------------------- |
| Method | `GET`                             |
| URL    | `http://localhost:5000/api/stats` |
| Body   | None                              |

**Expected Response**:

```json
{
  "vector_db": { "total_documents": 0 },
  "token_budget": { "used_today": 0, "daily_limit": 0, "remaining": 0 },
  "ai_provider": "gemini"
}
```

---

### 2.4 All Incidents

| Field  | Value                                 |
| ------ | ------------------------------------- |
| Method | `GET`                                 |
| URL    | `http://localhost:5000/api/incidents` |
| Body   | None                                  |

**Expected Response** (empty at start):

```json
{
  "incidents": [],
  "total": 0
}
```

---

## Phase 3: Webhook Endpoint (Jenkins Integration)

This is the **main entry point** that Jenkins calls on build failure.

### 3.1 Test Failure Webhook

| Field  | Value                                   |
| ------ | --------------------------------------- |
| Method | `POST`                                  |
| URL    | `http://localhost:5000/webhook/jenkins` |

**Body**:

```json
{
  "name": "Python-Test-Healing-Demo",
  "build": {
    "number": 25,
    "status": "FAILURE",
    "url": "http://jenkins:8080/job/Python-Test-Healing-Demo/25/"
  }
}
```

**Expected Response** (`200 OK`):

```json
{
  "healing_id": "a1b2c3d4",
  "status": "processing"
}
```

> [!IMPORTANT]
> This triggers the **full pipeline** in the background (LLM calls, Slack notifications, etc.). Check Docker logs for progress.

---

### 3.2 Skip Non-Failure (SUCCESS builds are ignored)

**Body**:

```json
{
  "name": "My-Build-Job",
  "build": {
    "number": 10,
    "status": "SUCCESS",
    "url": "http://jenkins:8080/job/My-Build-Job/10/"
  }
}
```

**Expected Response** (`200 OK`):

```json
{
  "healing_id": "xxxx",
  "status": "skipped_not_failure"
}
```

---

## Phase 4: Direct Heal API (Manual Trigger with Static Logs)

This is the **best endpoint for Postman testing** — you provide the error logs directly, so it doesn't need to reach Jenkins at all!

---

### 4.1 🧪 Test Failure — Python `pytest` AssertionError

| Field  | Value                            |
| ------ | -------------------------------- |
| Method | `POST`                           |
| URL    | `http://localhost:5000/api/heal` |

**Body**:

```json
{
  "job_name": "Postman-Test-Failure-Demo",
  "build_number": 101,
  "logs": "Running pytest...\n\n============================= test session starts =============================\nplatform linux -- Python 3.11.4, pytest-7.4.0\ncollected 5 items\n\ntests/test_api.py::test_login_success PASSED\ntests/test_api.py::test_login_invalid PASSED\ntests/test_api.py::test_user_profile FAILED\n\n=================================== FAILURES ===================================\n__________________________ test_user_profile ___________________________________\n\n    def test_user_profile():\n        response = client.get('/api/v1/profile', headers=auth_headers)\n>       assert response.status_code == 200\nE       AssertionError: assert 404 == 200\nE        +  where 404 = <Response [404]>.status_code\n\ntests/test_api.py:45: AssertionError\n========================= 1 failed, 2 passed in 3.21s ========================="
}
```

---

### 4.2 🧪 Compilation Error — Python `SyntaxError`

**Body**:

```json
{
  "job_name": "Postman-Compile-Error-Demo",
  "build_number": 102,
  "logs": "Step 5/8 : RUN pip install -r requirements.txt && python -m py_compile app/main.py\n\nCollecting flask==2.3.2\n  Downloading Flask-2.3.2.tar.gz (150 kB)\nInstalling collected packages: flask\nSuccessfully installed flask-2.3.2\n\n  File \"app/main.py\", line 23\n    def create_user(name, email\n                              ^\nSyntaxError: unexpected EOF while parsing\n\nERROR: process \"/bin/sh -c pip install -r requirements.txt && python -m py_compile app/main.py\" did not complete successfully: exit code: 1\nBUILD FAILURE"
}
```

---

### 4.3 🧪 Dependency Error — `ModuleNotFoundError`

**Body**:

```json
{
  "job_name": "Postman-Dependency-Error-Demo",
  "build_number": 103,
  "logs": "Installing dependencies...\nCollecting numpy==1.24.0\n  Using cached numpy-1.24.0.tar.gz\nCollecting pandas==2.0.0\n  Using cached pandas-2.0.0.tar.gz\n\nRunning application checks...\n\nTraceback (most recent call last):\n  File \"app/data_pipeline.py\", line 3, in <module>\n    import scikit_learn\nModuleNotFoundError: No module named 'scikit_learn'\n\nDid you mean: 'sklearn'?\nThe package name is 'scikit-learn', not 'scikit_learn'.\n\nHint: pip install scikit-learn\n\nBuild step 'Execute shell' marked build as failure\nFinished: FAILURE"
}
```

---

### 4.4 🧪 Configuration Error — Missing Environment Variable

**Body**:

```json
{
  "job_name": "Postman-Config-Error-Demo",
  "build_number": 104,
  "logs": "Starting application server...\nLoading configuration from environment...\n\nTraceback (most recent call last):\n  File \"app/server.py\", line 12, in <module>\n    db_url = os.environ['DATABASE_URL']\n  File \"/usr/lib/python3.11/os.py\", line 679, in __getitem__\n    raise KeyError(key) from None\nKeyError: 'DATABASE_URL'\n\nFATAL: Required environment variable DATABASE_URL is not set.\nPlease set DATABASE_URL in your Jenkins credentials or .env file.\nExample: DATABASE_URL=postgresql://user:pass@host:5432/mydb\n\nBuild step 'Execute shell' marked build as failure\nFinished: FAILURE"
}
```

---

### 4.5 🧪 Docker Build — Permission Denied

**Body**:

```json
{
  "job_name": "Postman-Docker-Permission-Demo",
  "build_number": 105,
  "logs": "Building Docker image...\nStep 1/6 : FROM python:3.11-slim\n ---> abc123def456\nStep 2/6 : WORKDIR /app\n ---> Using cache\nStep 3/6 : COPY . .\n ---> abc789ghi012\nStep 4/6 : RUN chmod +x scripts/start.sh\n ---> Running in 123abc456def\nchmod: changing permissions of 'scripts/start.sh': Operation not permitted\nThe command '/bin/sh -c chmod +x scripts/start.sh' returned a non-zero code: 1\n\nERROR: Service 'web' failed to build\ndocker-compose build exited with code 1\n\nBuild step 'Execute shell' marked build as failure\nFinished: FAILURE"
}
```

---

### 4.6 🧪 NPM / Node.js — TypeScript Type Error

**Body**:

```json
{
  "job_name": "Postman-TypeScript-Error-Demo",
  "build_number": 106,
  "logs": "Running: npm run build\n\n> my-app@1.0.0 build\n> tsc && vite build\n\nsrc/components/UserCard.tsx(18,5): error TS2322: Type 'string' is not assignable to type 'number'.\nsrc/components/UserCard.tsx(23,9): error TS2339: Property 'fullName' does not exist on type 'User'. Did you mean 'firstName'?\nsrc/utils/api.ts(45,3): error TS2345: Argument of type 'string' is not assignable to parameter of type 'RequestInit'.\n\nFound 3 errors in 2 files.\n\nnpm ERR! code ELIFECYCLE\nnpm ERR! errno 2\n\nBuild step 'Execute shell' marked build as failure\nFinished: FAILURE"
}
```

---

## Phase 5: Polling — Check Status & Result

After triggering any healing (Phase 3 or 4), use the returned `healing_id` to poll.

### 5.1 Check Healing Status

| Field  | Value                                                |
| ------ | ---------------------------------------------------- |
| Method | `GET`                                                |
| URL    | `http://localhost:5000/api/heal/{healing_id}/status` |

Replace `{healing_id}` with the actual ID (e.g., `a1b2c3d4`).

**Expected Response** (while processing):

```json
{
  "healing_id": "a1b2c3d4",
  "status": "running",
  "job_name": "Postman-Test-Failure-Demo",
  "build_number": 101
}
```

---

### 5.2 Get Final Result

| Field  | Value                                                |
| ------ | ---------------------------------------------------- |
| Method | `GET`                                                |
| URL    | `http://localhost:5000/api/heal/{healing_id}/result` |

**Expected Response** (when done):

```json
{
  "healing_id": "a1b2c3d4",
  "status": "done",
  "result": {
    "root_cause": "The /api/v1/profile endpoint is not registered...",
    "fix_description": "Add the missing route handler...",
    "fix_code": "@app.route('/api/v1/profile')\ndef profile():\n    ...",
    "final_confidence": 95,
    "resolution_mode": "READY_FIX",
    "loop_count": 1,
    "agents_used": [
      "LogParser",
      "GitDiff",
      "RootCause",
      "Fix",
      "Validator",
      "Notify"
    ],
    "total_tokens_used": 1250
  }
}
```

---

## Phase 6: Incident History (after running some heals)

### 6.1 View Single Incident

| Field  | Value                                               |
| ------ | --------------------------------------------------- |
| Method | `GET`                                               |
| URL    | `http://localhost:5000/api/incidents/{incident_id}` |

Replace `{incident_id}` with the value from the result (e.g., `19b59965`).

---

## 📋 Quick Reference — All Endpoints

| #   | Method | URL                                     | Purpose                   |
| --- | ------ | --------------------------------------- | ------------------------- |
| 1   | `GET`  | `/health`                               | Basic health check        |
| 2   | `GET`  | `/ready`                                | Readiness + ChromaDB      |
| 3   | `GET`  | `/api/config`                           | Engine configuration      |
| 4   | `GET`  | `/api/tokens`                           | Token usage today         |
| 5   | `GET`  | `/api/stats`                            | Vector DB + system stats  |
| 6   | `GET`  | `/api/incidents`                        | All past incidents        |
| 7   | `GET`  | `/api/incidents/{id}`                   | Single incident detail    |
| 8   | `POST` | `/webhook/jenkins`                      | Jenkins webhook trigger   |
| 9   | `POST` | `/api/heal`                             | Manual heal with logs     |
| 10  | `GET`  | `/api/heal/{id}/status`                 | Healing progress          |
| 11  | `GET`  | `/api/heal/{id}/result`                 | Healing final result      |
| 12  | `GET`  | `/api/approvals/{id}/approve?token=xxx` | Accept fix (Slack button) |
| 13  | `GET`  | `/api/approvals/{id}/decline?token=xxx` | Reject fix (Slack button) |

> [!CAUTION]
> Endpoints 12 & 13 require signed HMAC tokens — they are auto-generated by Slack buttons. Do NOT test manually.

---

## 🔄 Recommended Testing Flow

```
1. GET /health           → Verify engine is alive
2. GET /ready            → Verify ChromaDB is ready
3. GET /api/config       → Verify correct AI provider & thresholds
4. POST /api/heal        → Send Test Failure body (4.1)
5. GET /api/heal/{id}/status  → Poll until "done"
6. GET /api/heal/{id}/result  → View the AI's diagnosis & fix
7. GET /api/tokens       → Check token consumption
8. GET /api/incidents     → Verify incident was stored
9. POST /api/heal        → Send Compilation Error (4.2)
10. POST /api/heal       → Send Dependency Error (4.3)
11. GET /api/stats        → View cumulative stats
```
