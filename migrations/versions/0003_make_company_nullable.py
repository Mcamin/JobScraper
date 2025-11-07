"""make company column nullable"""

from alembic import op
import sqlalchemy as sa

# --- Alembic identifiers ---
revision = "0003_make_company_nullable"
down_revision = "0002_add_is_remote_and_applied_columns"
branch_labels = None
depends_on = None


def upgrade():
    """Make the 'company' column nullable in jobs table"""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "company",
            existing_type=sa.String(length=512),
            nullable=True
        )


def downgrade():
    """Revert the 'company' column back to NOT NULL"""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "company",
            existing_type=sa.String(length=512),
            nullable=False
        )
