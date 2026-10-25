"""The extraction eval: argument parsing, scoring, reporting, and the
refusal to run where real meeting content could be committed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.commitments import evaluation as ev
from app.sources.fathom import FathomMeeting
from tests.conftest import load_fixture

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_extraction.py"


def _script():
    spec = importlib.util.spec_from_file_location("eval_extraction", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_arguments():
    script = _script()
    args = script.parse_args([])
    assert args.fetch is None and args.model is None
    assert args.dir == script.DEFAULT_DIR
    args = script.parse_args(["--fetch", "5", "--model", "claude-haiku-5-5", "--threshold", "0.7"])
    assert (args.fetch, args.model, args.threshold) == (5, "claude-haiku-5-5", 0.7)


def test_precision_and_recall_on_a_hand_case():
    expected = ["Send Alice the revised budget", "Look at the volunteer form", "Book the venue"]
    found = [
        "Send Alice the revised budget by Thursday",
        "Review the volunteer form",
        "Email Jordan about parking",
        "Write the newsletter",
    ]
    s = ev.score(expected, found)
    assert (s.expected, s.found, s.matched) == (3, 4, 2)
    assert s.precision == 0.5
    assert round(s.recall, 3) == 0.667


def test_each_expected_item_matches_once():
    s = ev.score(["Send Alice the budget"], ["Send Alice the budget", "Send Alice the budget"])
    assert s.matched == 1 and s.precision == 0.5


def test_empty_lists_score_without_dividing_by_zero():
    s = ev.score([], [])
    assert s.precision is None and s.recall is None
    assert "n/a" in ev.format_score("x", s)


def test_vendor_baseline_keeps_only_items_assigned_to_the_recorder():
    raw = load_fixture("fathom/meeting_basic.json")
    raw["action_items"].append(
        {"description": "Alice books the venue", "assignee": {"name": "Alice Kim", "email": "alice@example.org"}}
    )
    meeting = FathomMeeting.model_validate(raw)
    assert ev.vendor_items_for(meeting) == ["Send revised budget to Alice"]


def test_report_groups_by_person_with_no_one_last():
    report = ev.group_report([
        {"summary": "Fix the footer", "counterparty": "Sam", "strength": "firm", "due_text": "this week"},
        {"summary": "Think about pricing", "counterparty": None, "strength": "soft"},
        {"summary": "Send the budget", "counterparty": "Alice", "strength": "firm"},
    ])
    lines = report.splitlines()
    assert [line.strip() for line in lines if not line.strip().startswith("-")] == [
        "Alice", "Sam", "No one in particular"
    ]
    assert "- [firm] Fix the footer (this week)" in report


def test_expected_file_accepts_list_or_object(tmp_path):
    a = tmp_path / "1.expected.json"
    a.write_text(json.dumps(["One", "Two"]))
    b = tmp_path / "2.expected.json"
    b.write_text(json.dumps({"commitments": ["Three"]}))
    assert ev.load_expected(a) == ["One", "Two"]
    assert ev.load_expected(b) == ["Three"]
    assert ev.load_expected(tmp_path / "missing.expected.json") is None


def test_saved_meeting_files_skip_expected_lists(tmp_path):
    for name in ("10.json", "10.expected.json", "11.json"):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in ev.saved_meeting_files(tmp_path)] == ["10.json", "11.json"]


def test_refuses_when_eval_dir_is_not_ignored(monkeypatch, tmp_path):
    script = _script()
    monkeypatch.setattr(script.ev, "is_git_ignored", lambda path: False)
    with pytest.raises(SystemExit) as excinfo:
        script.main(["--dir", str(tmp_path)])
    assert "not git-ignored" in str(excinfo.value)


def test_real_eval_dir_is_ignored_but_its_readme_is_not():
    eval_dir = SCRIPT.parents[1] / "eval"
    assert ev.is_git_ignored(eval_dir / "123.json")
    assert ev.is_git_ignored(eval_dir / "results" / "x.json")
    assert not ev.is_git_ignored(eval_dir / "README.md")
