"""Add explicit unit-basis pricing semantics.

Revision ID: 0006_unit_basis_pricing
Revises: 0005_offer_review_queue
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_unit_basis_pricing"
down_revision = "0005_offer_review_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offer_candidates",
        sa.Column("pricing_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "offer_candidates",
        sa.Column("regular_unit_price_eur", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "offer_candidates",
        sa.Column("example_weight_g", sa.Numeric(12, 2), nullable=True),
    )

    op.create_check_constraint(
        "ck_offer_candidates_pricing_mode",
        "offer_candidates",
        "pricing_mode IS NULL OR pricing_mode IN "
        "('fixed_package','unit_price_only','example_total_plus_unit',"
        "'app_example_total_plus_unit')",
    )
    op.create_check_constraint(
        "ck_offer_candidates_unit_basis_fields",
        "offer_candidates",
        "pricing_mode IS NULL OR pricing_mode = 'fixed_package' OR "
        "(unit_price_eur IS NOT NULL AND unit_label IS NOT NULL "
        "AND length(trim(unit_label)) > 0)",
    )
    op.create_check_constraint(
        "ck_offer_candidates_example_weight_positive",
        "offer_candidates",
        "example_weight_g IS NULL OR example_weight_g > 0",
    )
    op.create_check_constraint(
        "ck_offer_candidates_regular_unit_price_positive",
        "offer_candidates",
        "regular_unit_price_eur IS NULL OR regular_unit_price_eur > 0",
    )
    op.create_check_constraint(
        "ck_offer_candidates_example_mode_weight",
        "offer_candidates",
        "pricing_mode NOT IN ('example_total_plus_unit','app_example_total_plus_unit') "
        "OR example_weight_g IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_offer_candidates_app_example_requires_app",
        "offer_candidates",
        "pricing_mode <> 'app_example_total_plus_unit' OR requires_app = true",
    )


def downgrade() -> None:
    for name in (
        "ck_offer_candidates_app_example_requires_app",
        "ck_offer_candidates_example_mode_weight",
        "ck_offer_candidates_regular_unit_price_positive",
        "ck_offer_candidates_example_weight_positive",
        "ck_offer_candidates_unit_basis_fields",
        "ck_offer_candidates_pricing_mode",
    ):
        op.drop_constraint(name, "offer_candidates", type_="check")

    op.drop_column("offer_candidates", "example_weight_g")
    op.drop_column("offer_candidates", "regular_unit_price_eur")
    op.drop_column("offer_candidates", "pricing_mode")
