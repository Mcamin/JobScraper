"""create jobs table (extended with job_id, job_type, job_level, etc.)"""

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision = "0001_create_jobs_table"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("site_name", sa.String(length=64), nullable=False, index=True),
        sa.Column("search_term", sa.String(length=255), nullable=False, index=True),
        sa.Column("job_title", sa.String(length=512), nullable=False),
        sa.Column("company", sa.String(length=512), nullable=False, index=True),
        sa.Column("location", sa.String(length=255), nullable=False, index=True),
        sa.Column("job_url", sa.String(length=768), nullable=False, unique=True),

        # New fields
        sa.Column("job_type", sa.String(length=128), nullable=True),
        sa.Column("job_level", sa.String(length=128), nullable=True),
        sa.Column("emails", sa.Text(), nullable=True),
        sa.Column("company_industry", sa.String(length=255), nullable=True),
        sa.Column("company_url", sa.String(length=512), nullable=True),
        sa.Column("job_id", sa.String(length=255), nullable=True, index=True),

        # Existing fields
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("date_posted", sa.DateTime(), nullable=True),
        sa.Column("salary", sa.String(length=255), nullable=True),
        sa.Column("remote", sa.String(length=64), nullable=True),

        # Metadata
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )




def downgrade():
    op.drop_index("ix_jobs_job_id", table_name="jobs")
    op.drop_index("ix_jobs_location", table_name="jobs")
    op.drop_index("ix_jobs_company", table_name="jobs")
    op.drop_index("ix_jobs_search_term", table_name="jobs")
    op.drop_index("ix_jobs_site_name", table_name="jobs")
    op.drop_table("jobs")
