# 0002 — Extraction quality is measured by an eval, not by tests

**Status:** accepted
**Date:** 2026-10-25

## Context

Honor Code's value comes down to one judgment the code does not make: given a
meeting, did the model find the commitments Frank actually made, and only
those? Everything around that judgment (storing meetings, recording runs,
validating output, the review flow) is ordinary code and is tested the
ordinary way, with the model replaced by a fake that returns whatever a test
needs.

The judgment itself cannot be tested like that. A test that calls the real
model needs a key and the network, so it cannot run in CI (ADR 0001 keeps the
suite offline). Its answers vary from run to run, so a pass or fail would be
noise. And the only meetings worth measuring on are Frank's real calls, which
cannot be committed to a public repository.

## Decision

CI tests the app around the model, with the model faked at one seam
(`Extractor`). The model's judgment is measured by an opt-in script,
`apps/api/scripts/eval_extraction.py`, run by hand against real meetings
saved under `apps/api/eval/`. That folder is git-ignored except its README,
and the script refuses to run if that ever stops being true.

A round of the eval works like this: Frank writes down the commitments he
knows he made in a few meetings before looking at any output. The script
then runs extraction and scores each run against that list. It scores
Fathom's own action items the same way as a baseline. Every result records
the model and the prompt version.

## Consequences

- A prompt change is a code change that no test will catch. It bumps the
  prompt version and gets an eval round before it merges (CLAUDE.md says so).
- Choosing the default model is an eval question, answered with numbers from
  Frank's meetings rather than a guess.
- The fixtures in `tests/fixtures/` stay invented. A real meeting never
  enters the repository, even as a test case.
- The score is crude (loose summary matching). It compares runs with each
  other; it is not an absolute measure, and the found lists still get read.
