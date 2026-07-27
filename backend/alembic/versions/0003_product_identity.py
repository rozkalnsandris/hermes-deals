# revised Phase 3 product identity schema
#
# Revision ID: 0003_product_identity
# Revises: 0002_offer_persistence
# Create Date: 2026-07-25

from alembic import op
import sqlalchemy as sa


revision = "0003_product_identity"
down_revision = "0002_offer_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_normalizations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "offer_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("normalizer_version", sa.String(length=64), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("normalized_brand", sa.String(length=255), nullable=True),
        sa.Column("item_quantity_value", sa.Numeric(12, 4), nullable=True),
        sa.Column("item_quantity_unit", sa.String(length=32), nullable=True),
        sa.Column("pack_count", sa.Integer(), nullable=True),
        sa.Column("gtin14", sa.String(length=14), nullable=True),
        sa.Column("category_key", sa.String(length=128), nullable=True),
        sa.Column(
            "evidence_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "offer_candidate_id",
            "normalizer_version",
            name="uq_offer_normalizations_offer_version",
        ),
        sa.UniqueConstraint(
            "offer_candidate_id",
            "id",
            name="uq_offer_normalizations_offer_id_pair",
        ),
        sa.CheckConstraint(
            "length(trim(normalized_name)) > 0",
            name="ck_offer_normalizations_name_nonempty",
        ),
        sa.CheckConstraint(
            "item_quantity_value IS NULL OR item_quantity_value > 0",
            name="ck_offer_normalizations_quantity_positive",
        ),
        sa.CheckConstraint(
            "pack_count IS NULL OR pack_count > 0",
            name="ck_offer_normalizations_pack_count_positive",
        ),
        sa.CheckConstraint(
            "gtin14 IS NULL OR length(gtin14) = 14",
            name="ck_offer_normalizations_gtin14_length",
        ),
    )
    op.create_index(
        "ix_offer_normalizations_normalized_name",
        "offer_normalizations",
        ["normalized_name"],
    )
    op.create_index(
        "ix_offer_normalizations_normalized_brand",
        "offer_normalizations",
        ["normalized_brand"],
    )
    op.create_index(
        "ix_offer_normalizations_gtin14",
        "offer_normalizations",
        ["gtin14"],
    )

    op.create_table(
        "canonical_products",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("brand_display", sa.String(length=255), nullable=True),
        sa.Column("brand_normalized", sa.String(length=255), nullable=True),
        sa.Column("item_quantity_value", sa.Numeric(12, 4), nullable=True),
        sa.Column("item_quantity_unit", sa.String(length=32), nullable=True),
        sa.Column("pack_count", sa.Integer(), nullable=True),
        sa.Column("gtin14", sa.String(length=14), nullable=True),
        sa.Column("category_key", sa.String(length=128), nullable=True),
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
        sa.UniqueConstraint(
            "gtin14",
            name="uq_canonical_products_gtin14",
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0",
            name="ck_canonical_products_display_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(normalized_name)) > 0",
            name="ck_canonical_products_normalized_name_nonempty",
        ),
        sa.CheckConstraint(
            "item_quantity_value IS NULL OR item_quantity_value > 0",
            name="ck_canonical_products_quantity_positive",
        ),
        sa.CheckConstraint(
            "pack_count IS NULL OR pack_count > 0",
            name="ck_canonical_products_pack_count_positive",
        ),
        sa.CheckConstraint(
            "gtin14 IS NULL OR length(gtin14) = 14",
            name="ck_canonical_products_gtin14_length",
        ),
    )
    op.create_index(
        "ix_canonical_products_normalized_name",
        "canonical_products",
        ["normalized_name"],
    )
    op.create_index(
        "ix_canonical_products_name_brand",
        "canonical_products",
        ["normalized_name", "brand_normalized"],
    )

    op.create_table(
        "product_match_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "offer_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("offer_normalization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "canonical_product_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("matcher_version", sa.String(length=64), nullable=False),
        sa.Column("match_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "evidence_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["offer_candidate_id", "offer_normalization_id"],
            [
                "offer_normalizations.offer_candidate_id",
                "offer_normalizations.id",
            ],
            name="fk_match_candidates_offer_normalization",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "offer_normalization_id",
            "canonical_product_id",
            "matcher_version",
            name="uq_match_candidates_normalization_product_matcher",
        ),
        sa.UniqueConstraint(
            "offer_candidate_id",
            "canonical_product_id",
            "id",
            name="uq_match_candidates_offer_product_id",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_match_candidates_confidence",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_match_candidates_review_status",
        ),
        sa.CheckConstraint(
            "(review_status = 'pending' AND decided_at IS NULL) "
            "OR (review_status IN ('accepted', 'rejected') AND decided_at IS NOT NULL)",
            name="ck_match_candidates_decision_timestamp",
        ),
    )
    op.create_index(
        "ix_match_candidates_offer",
        "product_match_candidates",
        ["offer_candidate_id"],
    )
    op.create_index(
        "ix_match_candidates_product",
        "product_match_candidates",
        ["canonical_product_id"],
    )
    op.create_index(
        "ix_match_candidates_review_status",
        "product_match_candidates",
        ["review_status"],
    )

    op.create_table(
        "offer_product_links",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "offer_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("offer_candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "canonical_product_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_match_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("link_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "offer_candidate_id",
            name="uq_offer_product_links_offer_candidate",
        ),
        sa.ForeignKeyConstraint(
            [
                "offer_candidate_id",
                "canonical_product_id",
                "source_match_candidate_id",
            ],
            [
                "product_match_candidates.offer_candidate_id",
                "product_match_candidates.canonical_product_id",
                "product_match_candidates.id",
            ],
            name="fk_offer_links_source_match_candidate",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_offer_product_links_confidence",
        ),
    )
    op.create_index(
        "ix_offer_product_links_canonical_product",
        "offer_product_links",
        ["canonical_product_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_offer_product_links_canonical_product",
        table_name="offer_product_links",
    )
    op.drop_table("offer_product_links")

    op.drop_index(
        "ix_match_candidates_review_status",
        table_name="product_match_candidates",
    )
    op.drop_index(
        "ix_match_candidates_product",
        table_name="product_match_candidates",
    )
    op.drop_index(
        "ix_match_candidates_offer",
        table_name="product_match_candidates",
    )
    op.drop_table("product_match_candidates")

    op.drop_index(
        "ix_canonical_products_name_brand",
        table_name="canonical_products",
    )
    op.drop_index(
        "ix_canonical_products_normalized_name",
        table_name="canonical_products",
    )
    op.drop_table("canonical_products")

    op.drop_index(
        "ix_offer_normalizations_gtin14",
        table_name="offer_normalizations",
    )
    op.drop_index(
        "ix_offer_normalizations_normalized_brand",
        table_name="offer_normalizations",
    )
    op.drop_index(
        "ix_offer_normalizations_normalized_name",
        table_name="offer_normalizations",
    )
    op.drop_table("offer_normalizations")
