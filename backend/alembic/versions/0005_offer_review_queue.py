"""offer review queue

Revision ID: 0005_offer_review_queue
Revises: 0004_offer_app_validity
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_offer_review_queue"
down_revision = "0004_offer_app_validity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_chain", sa.String(length=32), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("source_flyer_key", sa.String(length=255), nullable=False),
        sa.Column("source_row_key", sa.String(length=255), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reason_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "original_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "corrected_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "provenance_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("published_offer_candidate_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["source_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_offer_candidate_id"],
            ["offer_candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_chain",
            "source_flyer_key",
            "source_row_key",
            name="uq_offer_review_items_source_row",
        ),
        sa.CheckConstraint(
            "status IN ('pending','draft','needs_followup','approved','rejected')",
            name="ck_offer_review_items_status",
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_offer_review_items_page_positive",
        ),
        sa.CheckConstraint(
            "(status = 'approved' AND published_offer_candidate_id IS NOT NULL AND decided_at IS NOT NULL) "
            "OR (status = 'rejected' AND published_offer_candidate_id IS NULL AND decided_at IS NOT NULL) "
            "OR (status IN ('pending','draft','needs_followup') "
            "AND published_offer_candidate_id IS NULL AND decided_at IS NULL)",
            name="ck_offer_review_items_decision_state",
        ),
    )
    op.create_index(
        "ix_offer_review_items_status",
        "offer_review_items",
        ["status"],
    )
    op.create_index(
        "ix_offer_review_items_source_chain",
        "offer_review_items",
        ["source_chain"],
    )
    op.create_index(
        "ix_offer_review_items_flyer_page",
        "offer_review_items",
        ["source_flyer_key", "page_number"],
    )

    op.create_table(
        "offer_review_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_item_id", sa.Uuid(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "payload_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["review_item_id"],
            ["offer_review_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_item_id",
            "revision_no",
            name="uq_offer_review_revisions_item_revision",
        ),
        sa.CheckConstraint(
            "revision_no > 0",
            name="ck_offer_review_revisions_revision_positive",
        ),
        sa.CheckConstraint(
            "action IN ('seed','draft','needs_followup','approve','reject','reopen')",
            name="ck_offer_review_revisions_action",
        ),
    )
    op.create_index(
        "ix_offer_review_revisions_item",
        "offer_review_revisions",
        ["review_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_offer_review_revisions_item",
        table_name="offer_review_revisions",
    )
    op.drop_table("offer_review_revisions")

    op.drop_index(
        "ix_offer_review_items_flyer_page",
        table_name="offer_review_items",
    )
    op.drop_index(
        "ix_offer_review_items_source_chain",
        table_name="offer_review_items",
    )
    op.drop_index(
        "ix_offer_review_items_status",
        table_name="offer_review_items",
    )
    op.drop_table("offer_review_items")
