"""phase 1 foundation

Revision ID: 0001_phase1
Revises:
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_phase1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("source_chain", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("content_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("snapshot_path", sa.Text(), nullable=True),
        sa.Column("keyword_hits", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("json_ld_blocks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("strategy_hint", sa.String(length=64), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_source_snapshots_chain_collected", "source_snapshots", ["source_chain", "collected_at"])

    op.create_table(
        "offer_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("source_chain", sa.String(length=32), nullable=False),
        sa.Column("source_store_external_id", sa.String(length=128), nullable=True),
        sa.Column("source_store_name", sa.String(length=255), nullable=True),
        sa.Column("source_offer_id", sa.String(length=255), nullable=True),
        sa.Column("product_name_raw", sa.Text(), nullable=False),
        sa.Column("brand_raw", sa.String(length=255), nullable=True),
        sa.Column("description_raw", sa.Text(), nullable=True),
        sa.Column("package_text_raw", sa.String(length=255), nullable=True),
        sa.Column("price_eur", sa.Numeric(10, 2), nullable=False),
        sa.Column("regular_price_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit_price_eur", sa.Numeric(12, 4), nullable=True),
        sa.Column("unit_label", sa.String(length=32), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("app_price_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("requires_app", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("coupon_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_image_url", sa.Text(), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index("ix_offer_candidates_chain_valid", "offer_candidates", ["source_chain", "valid_from", "valid_until"])


def downgrade() -> None:
    op.drop_index("ix_offer_candidates_chain_valid", table_name="offer_candidates")
    op.drop_table("offer_candidates")
    op.drop_index("ix_source_snapshots_chain_collected", table_name="source_snapshots")
    op.drop_table("source_snapshots")
