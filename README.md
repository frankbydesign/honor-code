# Honor Code

A personal app to track commitments extracted from Fathom transcripts (and, eventually, Gmail).

This repository is a monorepo containing:

- `apps/api` — FastAPI backend (Python 3.12+, managed with [uv](https://docs.astral.sh/uv/))
- `apps/web` — Angular frontend (standalone components + signals, managed with [pnpm](https://pnpm.io/))
- `docs/` — architecture and design notes

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for Python dependency management
- Node.js 20+ and [pnpm](https://pnpm.io/)

## Run the API locally

```bash
cd apps/api
uv run uvicorn app.main:app --reload
```

The API listens on http://localhost:8000. Verify with:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

## Run the web app locally

```bash
cd apps/web
pnpm install   # first time only
pnpm start
```

The Angular dev server listens on http://localhost:4200.

## Repository layout

```
honor-code/
├── apps/
│   ├── api/    # FastAPI app
│   └── web/    # Angular app
└── docs/
    └── architecture.md
```
