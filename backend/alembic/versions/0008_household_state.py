"""Add shared household state without modifying retailer observations."""
from alembic import op
import sqlalchemy as sa

revision = "0008_household_state"
down_revision = "0007_comparison_family_pricing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "household_states",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_household_state_version"),
    )


def downgrade():
    op.drop_table("household_states")
