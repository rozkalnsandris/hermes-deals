# offer candidate persistence hardening
#
# Revision ID: 0002_offer_persistence
# Revises: 0001_phase1
# Create Date: 2026-07-24

from alembic import op
import sqlalchemy as sa


revision = "0002_offer_persistence"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_offer_candidates_snapshot_offer"


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_groups = int(
        bind.execute(
            sa.text(
                """
                SELECT count(*)
                FROM (
                    SELECT snapshot_id, source_offer_id
                    FROM offer_candidates
                    WHERE source_offer_id IS NOT NULL
                    GROUP BY snapshot_id, source_offer_id
                    HAVING count(*) > 1
                ) AS duplicate_groups
                """
            )
        ).scalar_one()
    )
    if duplicate_groups:
        raise RuntimeError(
            "Cannot add offer candidate uniqueness constraint: "
            f"{duplicate_groups} duplicate group(s) exist"
        )

    op.create_unique_constraint(
        _CONSTRAINT,
        "offer_candidates",
        ["snapshot_id", "source_offer_id"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "offer_candidates", type_="unique")
