# 0001 — Local-first: one process, SQLite, no hosting

**Status:** accepted
**Date:** 2026-10-24

## Context

The original brief called for Angular on Vercel, FastAPI on Railway, and
Postgres. The first three working sessions delivered exactly that: a deployed,
authenticated, database-backed app with no product in it. Every hour went to
hosting (Railway, Postgres, Google Cloud, OAuth across two origins, Vercel
wiring) and none to the thing the app is for, which is extracting commitments
from transcripts and reviewing them. The split deployment also forced a layer
of complexity that existed only because the frontend and API lived on different
hosts: a CORS allowlist, glob patterns for Vercel preview URLs, a validated
`?next=` redirect, `SameSite=None` cookies, and a proxy that rewrote the OAuth
redirect URI to `http://`. The whole test suite at that point tested that layer
and nothing else.

Railway then had to be disconnected. Honor Code is a personal project, and the
only Vercel account connected is Center Point's, which should not carry it.
Nothing about developing the product requires it to be on the web.

## Decision

Honor Code runs on the owner's own machine as one process. FastAPI serves the
API under `/api` and the built Angular app from `/`. During frontend
development the Angular dev server serves `/` and proxies `/api`; either way
the browser sees one origin. The database is one SQLite file under
`apps/api/data/`, reached through aiosqlite, with models written in
dialect-neutral SQLAlchemy types (`Uuid`, `String`, and a `UTCDateTime`
decorator). Google OAuth login stays, because it is built, worked in
production, and the Gmail and Calendar integrations will reuse the same client.
One `APP_BASE_URL` drives the OAuth redirect URI and the cookie `Secure` flag;
plain `http` is accepted only for localhost.

No hosting target is chosen. The Vercel project on the Center Point team is
deleted, not kept idle. If Honor Code is ever hosted, it goes on a personal
account, and it keeps the same-origin shape (one process, or one reverse proxy
in front of both parts) rather than reintroducing a cross-origin split.

## Consequences

What this makes easy: `pytest` runs with no `.env`, no network, and nothing
running; `scripts/run.sh` is the whole operational surface; every
hosting-shaped concern (CORS, origin allowlists, preview URLs, proxy headers)
is gone from the code and from the test suite; feature work can start.

What it makes harder: the app is reachable only from the machine it runs on,
so there is no phone access and no sharing until a hosting decision is made.
SQLite is single-writer, which is irrelevant for one user and would matter for
more than one.

What it costs later: moving to Postgres means a new migration against the same
models, not a redesign; the neutral types are what keep that true, and the
rule that nothing imports from `sqlalchemy.dialects` must hold. Hosting means
choosing a personal account and either serving the built app from FastAPI
behind HTTPS (set `APP_BASE_URL` to the `https://` origin and nothing else
changes) or putting one reverse proxy in front of both. Re-splitting the
frontend and API onto different origins would bring back everything this
decision removed, and should be treated as a new ADR.
