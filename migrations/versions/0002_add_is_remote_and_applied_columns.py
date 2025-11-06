"""Add is_remote and applied columns; remove legacy 'remote'"""

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision = "0002_add_is_remote_and_applied_columns"
down_revision = "0001_create_jobs_table"
branch_labels = None
depends_on = None


def upgrade():
    # --- Add new boolean columns ---
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_remote", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false())
        )

        # Drop the old string-based remote column
        batch_op.drop_column("remote")


def downgrade():
    # --- Revert changes ---
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("remote", sa.String(length=64), nullable=True))
        batch_op.drop_column("is_remote")
        batch_op.drop_column("applied")
