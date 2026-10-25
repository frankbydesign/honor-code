"""Run extraction against your own saved Fathom meetings and score it.

    # Save your 5 most recent meetings into apps/api/eval/ (git-ignored):
    uv run --env-file .env python scripts/eval_extraction.py --fetch 5

    # Extract every saved meeting with the default model, then with Haiku:
    uv run --env-file .env python scripts/eval_extraction.py
    uv run --env-file .env python scripts/eval_extraction.py --model claude-haiku-5-5

For a score, write <recording_id>.expected.json next to a saved meeting
before looking at any output: a JSON list of the commitments you know you
made, one short line each. See eval/README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app import settings  # noqa: E402
from app.commitments import evaluation as ev  # noqa: E402
from app.commitments import transcript as tx  # noqa: E402
from app.commitments.extraction import (  # noqa: E402
    PROMPT_VERSION,
    AnthropicExtractor,
    ExtractionContext,
    build_user_message,
    system_prompt,
)
from app.commitments.schemas import ExtractionOutput  # noqa: E402
from app.sources.fathom import FathomClient, to_meeting_input  # noqa: E402

DEFAULT_DIR = API_DIR / "eval"
FETCH_LOOKBACK_DAYS = 90


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fetch", type=int, metavar="N", help="save your N most recent Fathom meetings, then stop")
    p.add_argument("--model", default=None, help="model to extract with (default: EXTRACTION_MODEL)")
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="where saved meetings live (default: apps/api/eval)")
    p.add_argument("--threshold", type=float, default=ev.MATCH_THRESHOLD, help="summary similarity counted as a match")
    return p.parse_args(argv)


def _refuse_unless_ignored(directory: Path) -> None:
    if not ev.is_git_ignored(directory / "probe.json"):
        sys.exit(
            f"refusing to run: {directory} is not git-ignored, so real meeting content could be committed. "
            "Check the eval/ entries in .gitignore."
        )


async def fetch(directory: Path, n: int) -> None:
    key = settings.fathom_api_key()
    if not key:
        sys.exit("FATHOM_API_KEY is not set")
    client = FathomClient(api_key=key)
    since = datetime.now(timezone.utc) - timedelta(days=FETCH_LOOKBACK_DAYS)
    meetings = sorted(await client.list_meetings(created_after=since), key=lambda m: m.created_at, reverse=True)[:n]
    directory.mkdir(parents=True, exist_ok=True)
    for m in meetings:
        items = await client.get_transcript(m.recording_id)
        path = directory / f"{m.recording_id}.json"
        path.write_text(
            json.dumps(
                {"meeting": m.model_dump(mode="json"), "transcript": [i.model_dump(mode="json") for i in items]},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"saved {path.name}: {m.title} ({len(items)} transcript lines)")


async def run(directory: Path, model: str, threshold: float) -> None:
    key = settings.anthropic_api_key()
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set")
    files = ev.saved_meeting_files(directory)
    if not files:
        sys.exit(f"no saved meetings in {directory}; run with --fetch N first")
    extractor = AnthropicExtractor(api_key=key, model=model, timeout=settings.extraction_timeout_seconds())
    tz = settings.local_timezone()
    results = []
    totals = {"input_tokens": 0, "output_tokens": 0}
    all_ours, all_vendor = [], []

    for path in files:
        meeting, transcript = ev.load_saved_meeting(path)
        mi = to_meeting_input(meeting, transcript)
        me = tx.identify_me(mi.segments, name=mi.recorded_by_name, email=mi.recorded_by_email)
        ctx = ExtractionContext(
            title=mi.title,
            meeting_date=tx.local_date(mi.occurred_at, tz),
            my_speaker=me,
            my_name=mi.recorded_by_name,
            my_email=mi.recorded_by_email,
        )
        result = await extractor.extract(system=system_prompt(), user=build_user_message(tx.render(mi.segments), ctx))
        found = [c.model_dump(mode="json") for c in ExtractionOutput.model_validate(result.raw).commitments]
        for c in found:
            c["quote_found"] = tx.quote_found(c["quote"], mi.segments)
        totals["input_tokens"] += result.input_tokens or 0
        totals["output_tokens"] += result.output_tokens or 0

        print(f"\n{mi.title} · {ctx.meeting_date} · you are {me or '(not matched)'}")
        print(ev.group_report(found))
        missing_quotes = sum(1 for c in found if not c["quote_found"])
        if missing_quotes:
            print(f"  {missing_quotes} quote(s) not found verbatim")

        record = {"file": path.name, "title": mi.title, "my_speaker": me, "found": found,
                  "input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
        expected = ev.load_expected(path.with_name(path.stem + ".expected.json"))
        if expected is not None:
            summaries = [c["summary"] for c in found]
            vendor = ev.vendor_items_for(meeting)
            ours, theirs = ev.score(expected, summaries, threshold), ev.score(expected, vendor, threshold)
            print(ev.format_score("Honor Code", ours))
            print(ev.format_score("Fathom action items", theirs))
            all_ours.append(ours)
            all_vendor.append(theirs)
            record["score"] = {"honor_code": vars(ours), "fathom": vars(theirs)}
        results.append(record)

    print(f"\n{len(files)} meetings · model {model} · prompt {PROMPT_VERSION}")
    print(f"tokens: {totals['input_tokens']} in, {totals['output_tokens']} out")
    if all_ours:
        def total(scores):
            return ev.Score(sum(s.expected for s in scores), sum(s.found for s in scores), sum(s.matched for s in scores))
        print(ev.format_score("Honor Code, all scored meetings", total(all_ours)))
        print(ev.format_score("Fathom, all scored meetings", total(all_vendor)))

    out_dir = directory / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"{stamp}-{model}-{PROMPT_VERSION}.json"
    out.write_text(json.dumps({"model": model, "prompt_version": PROMPT_VERSION, "threshold": threshold,
                               "totals": totals, "meetings": results}, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(API_DIR)}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _refuse_unless_ignored(args.dir)
    if args.fetch:
        asyncio.run(fetch(args.dir, args.fetch))
    else:
        asyncio.run(run(args.dir, args.model or settings.extraction_model(), args.threshold))


if __name__ == "__main__":
    main()
