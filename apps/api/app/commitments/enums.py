"""Allowed values for the String columns in the Phase 1 tables.

Stored as plain strings (dialect-neutral); validated in Python with these.
"""

from __future__ import annotations

from enum import StrEnum


class DocumentKind(StrEnum):
    FATHOM_MEETING = "fathom_meeting"


class CommitmentStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DONE = "done"
    DROPPED = "dropped"


class Strength(StrEnum):
    FIRM = "firm"
    SOFT = "soft"
    OFFER = "offer"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncTrigger(StrEnum):
    STARTUP = "startup"
    INTERVAL = "interval"
    MANUAL = "manual"
