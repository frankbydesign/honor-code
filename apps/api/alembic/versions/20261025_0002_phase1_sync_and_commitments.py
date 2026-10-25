"""phase 1: meetings, extraction runs, commitments, status events, sync runs

Revision ID: 0002_phase1
Revises: 0001_initial
Create Date: 2026-10-25

Dialect-neutral types, as in 0001: sa.Uuid, sa.DateTime(timezone=True),
sa.Date, sa.JSON, sa.String, sa.Text. Every foreign key is indexed and
cascades from its parent. The app supplies ids, timestamps, and defaults
from Python, so there are no server defaults.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase1"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("recorded_by_name", sa.String(length=200), nullable=True),
        sa.Column("recorded_by_email", sa.String(length=320), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("segments", sa.JSON(), nullable=False),
        sa.Column("speakers", sa.JSON(), nullable=False),
        sa.Column("my_speaker", sa.String(length=200), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("vendor_action_items", sa.JSON(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="source_documents_user_id_fkey", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "kind", "external_id", name="source_documents_user_kind_external_key"
        ),
    )
    op.create_index("ix_source_documents_user_id", "source_documents", ["user_id"])
    op.create_index("ix_source_documents_occurred_at", "source_documents", ["occurred_at"])

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("my_speaker", sa.String(length=200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name="extraction_runs_document_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_extraction_runs_document_id", "extraction_runs", ["document_id"])

    op.create_table(
        "commitments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=True),
        sa.Column("speaker", sa.String(length=200), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_found", sa.Boolean(), nullable=False),
        sa.Column("strength", sa.String(length=16), nullable=False),
        sa.Column("due_text", sa.String(length=200), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name="commitments_document_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["extraction_runs.id"], name="commitments_run_id_fkey", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_commitments_document_id", "commitments", ["document_id"])
    op.create_index("ix_commitments_run_id", "commitments", ["run_id"])
    op.create_index("ix_commitments_status", "commitments", ["status"])

    op.create_table(
        "status_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("commitment_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["commitments.id"],
            name="status_events_commitment_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_status_events_commitment_id", "status_events", ["commitment_id"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meetings_seen", sa.Integer(), nullable=False),
        sa.Column("meetings_new", sa.Integer(), nullable=False),
        sa.Column("meetings_pending", sa.Integer(), nullable=False),
        sa.Column("extractions_ok", sa.Integer(), nullable=False),
        sa.Column("extractions_failed", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_sync_runs_started_at", "sync_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_sync_runs_started_at", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_index("ix_status_events_commitment_id", table_name="status_events")
    op.drop_table("status_events")
    op.drop_index("ix_commitments_status", table_name="commitments")
    op.drop_index("ix_commitments_run_id", table_name="commitments")
    op.drop_index("ix_commitments_document_id", table_name="commitments")
    op.drop_table("commitments")
    op.drop_index("ix_extraction_runs_document_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    op.drop_index("ix_source_documents_occurred_at", table_name="source_documents")
    op.drop_index("ix_source_documents_user_id", table_name="source_documents")
    op.drop_table("source_documents")
