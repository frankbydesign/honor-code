# CLAUDE.md

Operating notes for Claude (and future contributors) working in this repo.

## Project

Honor Code is a personal app that extracts and tracks commitments from
Fathom transcripts (and, eventually, Gmail). It is a single-user, single-developer
project at low traffic. Optimize for clarity and small focused changes, not scale.

## Repo layout

- `apps/api` — FastAPI backend, Python 3.12+, managed with `uv`
- `apps/web` — Angular frontend, standalone components + signals, managed with `pnpm`
- `docs/` — architecture and design notes

## Session protocol

1. **Read the task description carefully.** Stop at the scope boundary the task
   defines. Do not deploy, add CI, add Docker, add a database, or add auth unless
   the task explicitly asks for it.
2. **Keep diffs small and focused.** Scaffolding tasks should produce
   scaffolding only. Feature tasks should not refactor unrelated code.
3. **Never commit secrets.** No `.env` files, no API keys, no credentials.
   The `.gitignore` covers `.env`, `.env.local`, and `.env.*.local`.
4. **Verify before reporting done.** For backend changes, hit the endpoint
   with `curl`. For frontend changes, load the page in a browser (or `curl`
   the dev server) and confirm it renders.
5. **Use the right tooling.**
   - Python: `uv` only. Add deps with `uv add <pkg>`. Run with `uv run ...`.
   - Node: `pnpm` only. Add deps with `pnpm add <pkg>`.
6. **Angular conventions.** Standalone components only — no NgModules.
   Use Angular Signals for component state.

## Commands

Run the API:

```bash
cd apps/api && uv run uvicorn app.main:app --reload
```

Run the web app:

```bash
cd apps/web && pnpm start
```

## What's intentionally out of scope (for now)

- Authentication
- Database / persistence
- Deployment / hosting
- CI / GitHub Actions
- Docker / containers
- External API integrations (Fathom, Gmail)

These will be added in future tasks.
