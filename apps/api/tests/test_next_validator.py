"""Integration tests for the `?next=` validator wired through router.py.

The conftest sets FRONTEND_ORIGINS to https://app.example.com and
FRONTEND_ORIGINS_PATTERNS to https://honor-code-*-cpdigital.vercel.app.
"""

from __future__ import annotations

from app.auth.router import _validate_next_url


# Exact-match path — unchanged behavior.

def test_exact_match_origin_is_accepted():
    assert (
        _validate_next_url("https://app.example.com/")
        == "https://app.example.com/"
    )


def test_path_and_query_preserved_for_exact_match():
    result = _validate_next_url("https://app.example.com/foo?bar=1")
    assert result == "https://app.example.com/foo?bar=1"


# Pattern path — new behavior.

def test_pattern_match_deployment_hash_url_is_accepted():
    url = "https://honor-code-4e3z8fp64-cpdigital.vercel.app/"
    assert _validate_next_url(url) == url


def test_pattern_match_branch_alias_url_is_accepted():
    url = "https://honor-code-git-feat-login-ui-cpdigital.vercel.app/"
    assert _validate_next_url(url) == url


def test_pattern_match_with_path_is_accepted_and_preserved():
    url = "https://honor-code-abc-cpdigital.vercel.app/auth/return?x=1"
    assert _validate_next_url(url) == url


# Negative path.

def test_unrelated_origin_is_rejected():
    assert _validate_next_url("https://evil.com/") is None


def test_substring_team_attack_is_rejected():
    # `cpdigitalevil` is a different team slug.
    url = "https://honor-code-X-cpdigitalevil.vercel.app/"
    assert _validate_next_url(url) is None


def test_different_project_prefix_is_rejected():
    url = "https://different-project-cpdigital.vercel.app/"
    assert _validate_next_url(url) is None


def test_userinfo_bypass_is_rejected():
    # If `*` matched across `@`, this would let an attacker control
    # the destination host. Userinfo must be refused outright.
    url = "https://honor-code-X@evil.com-cpdigital.vercel.app/"
    assert _validate_next_url(url) is None


def test_fragment_with_at_does_not_smuggle_pattern_match():
    # `urlsplit` parses everything after `#` as fragment, so the
    # origin extracted is `https://evil.com` and exact-match fails.
    url = "https://evil.com#@honor-code-X-cpdigital.vercel.app/"
    assert _validate_next_url(url) is None


def test_missing_scheme_is_rejected():
    assert _validate_next_url("honor-code-X-cpdigital.vercel.app") is None


def test_protocol_relative_url_is_rejected():
    assert _validate_next_url("//honor-code-X-cpdigital.vercel.app/") is None
