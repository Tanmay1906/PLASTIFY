# PLASTIFY — Backend Architecture & Operations Guide

See the root [README.md](../README.md) for full project architecture and API documentation.

### Quick Start (Local Backend)

```bash
# 1. Activate Virtual Environment
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # Linux / macOS

# 2. Run Tests
pytest -v

# 3. Apply Migrations (PostgreSQL)
alembic upgrade head

# 4. Start Development Server
uvicorn app.main:app --reload --port 8000

# 5. Run Celery Worker
celery -A app.workers.celery_app worker --loglevel=INFO
```

### Docker Quick Start

```bash
# Start all services (API, Worker, PostgreSQL, Redis)
docker compose up --build -d
```
