"""Record PDF acquisition evidence without changing source observations."""
from alembic import op
import sqlalchemy as sa

revision = "0009_pdf_acquisitions"
down_revision = "0008_household_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pdf_acquisitions",
        sa.Column("pdf_sha256", sa.String(64), primary_key=True),
        sa.Column("evidence_ref", sa.String(255), primary_key=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(pdf_sha256) = 64 AND lower(pdf_sha256) = pdf_sha256",
                           name="ck_pdf_acquisitions_sha"),
        sa.CheckConstraint("length(trim(evidence_ref)) > 0",
                           name="ck_pdf_acquisitions_evidence"),
        sa.CheckConstraint("acquired_at IS NULL OR acquired_at <= recorded_at",
                           name="ck_pdf_acquisitions_time_order"),
    )


def downgrade():
    op.drop_table("pdf_acquisitions")
