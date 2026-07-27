# Add app-specific offer validity.
#
# Revision ID: 0004_offer_app_validity
# Revises: 0003_product_identity
# Create Date: 2026-07-27

from alembic import op
import sqlalchemy as sa


revision = "0004_offer_app_validity"
down_revision = "0003_product_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("offer_candidates", sa.Column("app_valid_from", sa.Date(), nullable=True))
    op.add_column("offer_candidates", sa.Column("app_valid_until", sa.Date(), nullable=True))

    op.create_check_constraint(
        "ck_offer_candidates_app_validity_pair",
        "offer_candidates",
        "(app_valid_from IS NULL AND app_valid_until IS NULL) OR "
        "(app_valid_from IS NOT NULL AND app_valid_until IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_offer_candidates_app_validity_order",
        "offer_candidates",
        "app_valid_from IS NULL OR app_valid_until >= app_valid_from",
    )
    op.create_check_constraint(
        "ck_offer_candidates_app_validity_requires_price",
        "offer_candidates",
        "app_valid_from IS NULL OR app_price_eur IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_offer_candidates_app_validity_requires_price",
        "offer_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_offer_candidates_app_validity_order",
        "offer_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_offer_candidates_app_validity_pair",
        "offer_candidates",
        type_="check",
    )
    op.drop_column("offer_candidates", "app_valid_until")
    op.drop_column("offer_candidates", "app_valid_from")
