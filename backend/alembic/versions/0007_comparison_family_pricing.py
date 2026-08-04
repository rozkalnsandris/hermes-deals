"""Add comparison families and immutable pricing normalizations.

Revision ID: 0007_comparison_family_pricing
Revises: 0006_unit_basis_pricing
Create Date: 2026-08-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_comparison_family_pricing"
down_revision: Union[str, None] = "0006_unit_basis_pricing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "offer_pricing_normalizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offer_candidate_id", sa.Uuid(), nullable=False),
        sa.Column("normalizer_version", sa.String(length=64), nullable=False),
        sa.Column("pricing_mode", sa.String(length=32), nullable=False),
        sa.Column(
            "advertised_price_eur",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
        ),
        sa.Column(
            "basis_quantity_value",
            sa.Numeric(precision=12, scale=4),
            nullable=True,
        ),
        sa.Column(
            "basis_quantity_unit",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "normalized_unit_price_eur",
            sa.Numeric(precision=12, scale=4),
            nullable=True,
        ),
        sa.Column(
            "fixed_item_quantity_value",
            sa.Numeric(precision=12, scale=4),
            nullable=True,
        ),
        sa.Column(
            "fixed_item_quantity_unit",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
        ),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pricing_mode IN "
            "('fixed_package','variable_weight','piece',"
            "'unit_price_only','unknown')",
            name="ck_offer_pricing_normalizations_mode",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_offer_pricing_normalizations_confidence",
        ),
        sa.CheckConstraint(
            "advertised_price_eur > 0",
            name="ck_offer_pricing_normalizations_advertised_price",
        ),
        sa.CheckConstraint(
            "basis_quantity_value IS NULL OR basis_quantity_value > 0",
            name="ck_offer_pricing_normalizations_basis_positive",
        ),
        sa.CheckConstraint(
            "basis_quantity_unit IS NULL OR "
            "basis_quantity_unit IN ('kg','l','piece')",
            name="ck_offer_pricing_normalizations_basis_unit",
        ),
        sa.CheckConstraint(
            "fixed_item_quantity_value IS NULL "
            "OR fixed_item_quantity_value > 0",
            name="ck_offer_pricing_normalizations_fixed_quantity",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','accepted','rejected')",
            name="ck_offer_pricing_normalizations_review",
        ),
        sa.CheckConstraint(
            "review_status <> 'accepted' OR "
            "(pricing_mode <> 'unknown' "
            "AND normalized_unit_price_eur IS NOT NULL)",
            name="ck_offer_pricing_normalizations_accepted_ready",
        ),
        sa.CheckConstraint(
            "normalized_unit_price_eur IS NULL "
            "OR normalized_unit_price_eur > 0",
            name="ck_offer_pricing_normalizations_unit_price",
        ),
        sa.CheckConstraint(
            "pricing_mode <> 'variable_weight' OR "
            "(basis_quantity_value IS NOT NULL "
            "AND basis_quantity_unit = 'kg' "
            "AND fixed_item_quantity_value IS NULL "
            "AND fixed_item_quantity_unit IS NULL)",
            name="ck_offer_pricing_normalizations_variable_weight",
        ),
        sa.ForeignKeyConstraint(
            ["offer_candidate_id"],
            ["offer_candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "offer_candidate_id",
            name="uq_offer_pricing_normalizations_offer",
        ),
    )
    op.create_index(
        "ix_offer_pricing_normalizations_mode_review",
        "offer_pricing_normalizations",
        ["pricing_mode", "review_status"],
        unique=False,
    )

    op.create_table(
        "comparison_families",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("variant_key", sa.String(length=128), nullable=True),
        sa.Column(
            "comparison_dimension",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "basis_quantity_value",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
        ),
        sa.Column(
            "basis_quantity_unit",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(family_key)) > 0",
            name="ck_comparison_families_key_nonempty",
        ),
        sa.CheckConstraint(
            "comparison_dimension IN ('mass','volume','count')",
            name="ck_comparison_families_dimension",
        ),
        sa.CheckConstraint(
            "basis_quantity_value > 0",
            name="ck_comparison_families_basis_positive",
        ),
        sa.CheckConstraint(
            "(comparison_dimension = 'mass' "
            "AND basis_quantity_unit = 'g') OR "
            "(comparison_dimension = 'volume' "
            "AND basis_quantity_unit = 'ml') OR "
            "(comparison_dimension = 'count' "
            "AND basis_quantity_unit = 'count')",
            name="ck_comparison_families_basis_compatible",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','active','retired',"
            "'blocked_until_pricing_normalization')",
            name="ck_comparison_families_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "family_key",
            name="uq_comparison_families_family_key",
        ),
    )
    op.create_index(
        "ix_comparison_families_name_variant",
        "comparison_families",
        ["normalized_name", "variant_key"],
        unique=False,
    )

    op.create_table(
        "comparison_family_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("comparison_family_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_product_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column(
            "membership_method",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
        ),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "relation_type IN ('direct_peer','substitute')",
            name="ck_comparison_family_members_relation",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_comparison_family_members_confidence",
        ),
        sa.CheckConstraint(
            "membership_method IN ('human_source_review','rule')",
            name="ck_comparison_family_members_method",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','accepted','rejected')",
            name="ck_comparison_family_members_review",
        ),
        sa.CheckConstraint(
            "(review_status = 'pending' AND decided_at IS NULL) OR "
            "(review_status IN ('accepted','rejected') "
            "AND decided_at IS NOT NULL)",
            name="ck_comparison_family_members_decision",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_product_id"],
            ["canonical_products.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_family_id"],
            ["comparison_families.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_family_id",
            "canonical_product_id",
            name="uq_comparison_family_members_family_product",
        ),
    )
    op.create_index(
        "ix_comparison_family_members_product",
        "comparison_family_members",
        ["canonical_product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_comparison_family_members_product",
        table_name="comparison_family_members",
    )
    op.drop_table("comparison_family_members")
    op.drop_index(
        "ix_comparison_families_name_variant",
        table_name="comparison_families",
    )
    op.drop_table("comparison_families")
    op.drop_index(
        "ix_offer_pricing_normalizations_mode_review",
        table_name="offer_pricing_normalizations",
    )
    op.drop_table("offer_pricing_normalizations")
