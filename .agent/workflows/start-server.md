---
description: Start the AnesLog local development server with seed data
---

// turbo-all

## Start the local dev server

1. Seed the database with demo data (idempotent — skips if data already exists):
```bash
source .venv/bin/activate && python -m app.seed
```

2. Start the FastAPI server with hot-reload on port 8000:
```bash
source .venv/bin/activate && uvicorn app.main:app --reload --port 8000
```
This is a long-running command; send it to the background after ~3 seconds.

The server will be available at **http://127.0.0.1:8000**.
