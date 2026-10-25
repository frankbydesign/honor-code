# 0003 — Poll Fathom from the running app

**Status:** accepted
**Date:** 2026-10-25

## Context

Honor Code is meant to collect commitments without any copying and pasting:
meetings should show up and be read on their own. Fathom offers two ways to
get new meetings out. A webhook pushes each meeting the moment Fathom
finishes processing it. The external API lets a client list meetings created
after a given time and fetch each transcript.

A webhook needs a public URL that Fathom can reach. ADR 0001 rules out
hosting: the app runs on one machine, on localhost. Getting a public URL
would mean a tunnel or a hosted receiver, which brings back exactly the
deployment work ADR 0001 removed. A background agent (launchd) could poll
while the app is closed, but that is packaging, which ADR 0001 also rules out
for now.

## Decision

The running app polls Fathom itself: once a few seconds after startup, then
every `FATHOM_SYNC_INTERVAL_MINUTES` (default 30) while it runs, and when
the user presses Sync now. Each sync lists meetings created since a window
start, stores the ones it has not seen (deduplicated by Fathom recording
id), and extracts commitments from each new meeting.

The first sync reaches `FATHOM_BACKFILL_DAYS` (default 14) back. Later syncs
start 48 hours before the start of the last successful sync, so a meeting
Fathom processed late is still caught. When a sync leaves meetings pending
because their transcripts were not ready, the next window reaches back to
that sync's own start, capped at the backfill, so no meeting falls out of
range while it waits.

## Consequences

- Meetings arrive only while the app is open. Opening the app after a few
  days of calls means a short wait while it catches up.
- No public URL, no tunnel, no webhook secret to manage, nothing new to
  host. The Fathom key lives in `apps/api/.env` like every other secret.
- Polling every 30 minutes costs a handful of requests per hour, far below
  Fathom's limit of 60 per minute.
- Moving to webhooks later means a hosted receiver, which would amend ADR
  0001. A launchd agent that runs the same sync while the app is closed is
  the smaller step if the wait at startup turns out to matter.
