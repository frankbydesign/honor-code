# Extraction eval data

This folder holds real meetings for measuring how well extraction works. Everything in it except this file is git-ignored, because it is the content of real calls. The eval script refuses to run if that ever stops being true.

The tests can only prove the app handles whatever the model returns. Whether the model finds the right commitments can only be judged against meetings where you know what you promised. ADR 0002 has the reasoning.

## Doing a round

1. Save some meetings: `uv run --env-file .env python scripts/eval_extraction.py --fetch 5` (from `apps/api`). Each lands here as `<recording_id>.json`.
2. Before looking at any output, write `<recording_id>.expected.json` for two or three of them: a JSON list of the commitments you know you made, one short line each, like `["Send Alice the revised budget", "Look at the volunteer form"]`. Writing it first keeps the list honest.
3. Run it: `uv run --env-file .env python scripts/eval_extraction.py`. Then again with `--model claude-haiku-5-5`.
4. Read the output. Each meeting prints what was found, grouped by person, and, where you wrote an expected list, how many of yours were matched (recall) and how many of the found ones were real (precision), for Honor Code and for Fathom's own action items. Results are saved under `results/`, named by time, model and prompt version.

Matching compares summaries loosely (`--threshold`, default 0.6), so read the found list yourself too. The score is for comparing runs against each other; on its own it says little.

## When you change the prompt

Copy `app/commitments/prompts/v1.md` to `v2.md`, change it, set `PROMPT_VERSION = "v2"` in `app/commitments/extraction.py`, and run a round. Keep v1 so the comparison stays possible.
