"""Frontend-origin allowlist primitives shared by CORS and `?next=` validation.

Two layers:

- `FRONTEND_ORIGINS` (exact match) — the existing list of full origins.
- `FRONTEND_ORIGINS_PATTERNS` (glob match) — patterns where `*` is the
  only wildcard. Used for Vercel Preview URLs whose hostnames change
  per deployment but follow a stable team/project shape.

The CORS middleware and the `?next=` validator both consult both
layers, so an origin allowed for the OAuth redirect is also allowed
for the post-login credentialed `/auth/me` fetch.
"""

from __future__ import annotations

import re


def validate_pattern(pattern: str) -> None:
    """Raise RuntimeError if a pattern is unsafely open-ended.

    Rejects: leading `*`, trailing `*`, missing scheme. Operator
    discipline is required for non-open-ended-but-still-permissive
    patterns (e.g. `https://*.vercel.app`).
    """
    if not pattern:
        raise RuntimeError("FRONTEND_ORIGINS_PATTERNS contains an empty entry")
    if pattern.startswith("*") or pattern.endswith("*"):
        raise RuntimeError(
            f"FRONTEND_ORIGINS_PATTERNS entry {pattern!r} has a leading "
            "or trailing wildcard, which is too permissive"
        )
    if "://" not in pattern:
        raise RuntimeError(
            f"FRONTEND_ORIGINS_PATTERNS entry {pattern!r} must include a "
            "scheme like https:// (no path, no trailing slash)"
        )


def parse_patterns_env(raw: str) -> tuple[str, ...]:
    """Split a comma/whitespace env value into validated patterns.

    Empty/blank input yields an empty tuple — pattern matching is
    purely additive.
    """
    if not raw or not raw.strip():
        return ()
    patterns = tuple(
        p.strip().rstrip("/")
        for p in raw.replace(",", " ").split()
        if p.strip()
    )
    for p in patterns:
        validate_pattern(p)
    return patterns


def _glob_to_regex(pattern: str) -> str:
    # `*` is the only wildcard; everything else is literal. We escape
    # each segment between `*`s and join with `.*`. Starlette's CORS
    # middleware uses re.fullmatch, so anchors are not required, but
    # we add them so the same compiled regex is safe for ad-hoc
    # callers using `.search` or `.match`.
    parts = pattern.split("*")
    return "^" + ".*".join(re.escape(p) for p in parts) + "$"


def compile_patterns(patterns: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile a tuple of validated patterns into one combined regex.

    Returns None when the tuple is empty so callers (and Starlette)
    can short-circuit.
    """
    if not patterns:
        return None
    combined = "|".join(f"(?:{_glob_to_regex(p)})" for p in patterns)
    return re.compile(combined)


def origin_matches(
    origin: str,
    exact: tuple[str, ...],
    compiled: re.Pattern[str] | None,
) -> bool:
    """Check exact-match list, then pattern regex."""
    if origin in exact:
        return True
    if compiled is not None and compiled.fullmatch(origin):
        return True
    return False
