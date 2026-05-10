"""Unit tests for the pure helpers in app.auth.origins.

These don't import any module that requires env vars, so they run
without needing the conftest defaults — but the conftest sets them
anyway, which is fine.
"""

from __future__ import annotations

import pytest

from app.auth.origins import (
    compile_patterns,
    origin_matches,
    parse_patterns_env,
    validate_pattern,
)


def test_validate_pattern_accepts_middle_wildcard():
    validate_pattern("https://honor-code-*-cpdigital.vercel.app")


def test_validate_pattern_accepts_multiple_middle_wildcards():
    validate_pattern("https://honor-code-*-cpdigital-*.vercel.app")


@pytest.mark.parametrize(
    "bad",
    [
        "*",
        "*-cpdigital.vercel.app",
        "https://honor-code-*",
        "*.vercel.app",
        "https://*",
    ],
)
def test_validate_pattern_rejects_open_ended(bad: str):
    with pytest.raises(RuntimeError, match="leading or trailing wildcard"):
        validate_pattern(bad)


def test_validate_pattern_requires_scheme():
    with pytest.raises(RuntimeError, match="must include a scheme"):
        validate_pattern("honor-code-*-cpdigital.vercel.app")


def test_parse_patterns_env_empty_returns_empty_tuple():
    assert parse_patterns_env("") == ()
    assert parse_patterns_env("   ") == ()


def test_parse_patterns_env_splits_on_whitespace_and_commas():
    raw = (
        "https://honor-code-*-cpdigital.vercel.app, "
        "https://staging-*.example.com"
    )
    assert parse_patterns_env(raw) == (
        "https://honor-code-*-cpdigital.vercel.app",
        "https://staging-*.example.com",
    )


def test_parse_patterns_env_strips_trailing_slash():
    assert parse_patterns_env("https://honor-code-*-cpdigital.vercel.app/") == (
        "https://honor-code-*-cpdigital.vercel.app",
    )


def test_parse_patterns_env_raises_on_unsafe_pattern():
    with pytest.raises(RuntimeError, match="leading or trailing wildcard"):
        parse_patterns_env("https://honor-code-*-cpdigital.vercel.app, *")


def test_compile_patterns_returns_none_for_empty():
    assert compile_patterns(()) is None


def test_compile_patterns_matches_substituted_wildcard():
    compiled = compile_patterns(("https://honor-code-*-cpdigital.vercel.app",))
    assert compiled is not None
    assert compiled.fullmatch(
        "https://honor-code-4e3z8fp64-cpdigital.vercel.app"
    )
    assert compiled.fullmatch(
        "https://honor-code-git-feat-login-ui-cpdigital.vercel.app"
    )


def test_compile_patterns_rejects_substring_team_match():
    # `cpdigitalevil` is a different team slug — anchored fullmatch
    # must not let it through.
    compiled = compile_patterns(("https://honor-code-*-cpdigital.vercel.app",))
    assert compiled is not None
    assert not compiled.fullmatch(
        "https://honor-code-X-cpdigitalevil.vercel.app"
    )


def test_compile_patterns_rejects_different_project_prefix():
    compiled = compile_patterns(("https://honor-code-*-cpdigital.vercel.app",))
    assert compiled is not None
    assert not compiled.fullmatch(
        "https://different-project-cpdigital.vercel.app"
    )


def test_compile_patterns_rejects_trailing_extra():
    compiled = compile_patterns(("https://honor-code-*-cpdigital.vercel.app",))
    assert compiled is not None
    assert not compiled.fullmatch(
        "https://honor-code-X-cpdigital.vercel.app.evil.com"
    )


def test_compile_patterns_does_not_treat_question_mark_as_wildcard():
    # fnmatch.translate would treat `?` as a single-char wildcard; our
    # custom converter must not.
    compiled = compile_patterns(("https://honor-code-?.vercel.app",))
    assert compiled is not None
    # The literal `?` is unlikely in a real hostname; what matters is
    # that an arbitrary single char isn't accepted as a `?` substitute.
    assert not compiled.fullmatch("https://honor-code-X.vercel.app")
    assert compiled.fullmatch("https://honor-code-?.vercel.app")


def test_compile_patterns_combines_multiple():
    compiled = compile_patterns(
        (
            "https://honor-code-*-cpdigital.vercel.app",
            "https://staging-*.example.com",
        )
    )
    assert compiled is not None
    assert compiled.fullmatch("https://honor-code-abc-cpdigital.vercel.app")
    assert compiled.fullmatch("https://staging-eu.example.com")
    assert not compiled.fullmatch("https://prod.example.com")


def test_origin_matches_exact_only():
    assert origin_matches(
        "https://app.example.com", ("https://app.example.com",), None
    )
    assert not origin_matches(
        "https://other.example.com", ("https://app.example.com",), None
    )


def test_origin_matches_pattern_only():
    compiled = compile_patterns(("https://honor-code-*-cpdigital.vercel.app",))
    assert origin_matches(
        "https://honor-code-X-cpdigital.vercel.app", (), compiled
    )
    assert not origin_matches("https://evil.com", (), compiled)


def test_origin_matches_combined_layers():
    compiled = compile_patterns(("https://honor-code-*-cpdigital.vercel.app",))
    exact = ("https://app.example.com",)
    assert origin_matches("https://app.example.com", exact, compiled)
    assert origin_matches(
        "https://honor-code-X-cpdigital.vercel.app", exact, compiled
    )
    assert not origin_matches("https://evil.com", exact, compiled)
