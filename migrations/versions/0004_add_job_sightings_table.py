"""add job_sightings table (debug_duplicates history)"""

from alembic import op
import sqlalchemy as sa

# --- Alembic identifiers ---
revision = "0004_add_job_sightings_table"
down_revision = "0003_make_company_nullable"
branch_labels = None
depends_on = None


def upgrade():
    """Create job_sightings: one row each time a debug scrape returns a stored job again."""
    op.create_table(
        "job_sightings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_pk",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seen_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("site_name", sa.String(length=64), nullable=True),
        sa.Column("search_term", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("hours_old", sa.Integer(), nullable=True),
        sa.Column("scraped_date_posted", sa.DateTime(), nullable=True),
        sa.Column("stored_date_posted", sa.DateTime(), nullable=True),
        sa.Column("first_scraped_at", sa.DateTime(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_job_sightings_job_pk", "job_sightings", ["job_pk"])
    op.create_index("ix_job_sightings_seen_at", "job_sightings", ["seen_at"])
    op.create_index("ix_job_sightings_search_term", "job_sightings", ["search_term"])
    op.create_index("ix_job_sightings_reason", "job_sightings", ["reason"])


def downgrade():
    """Drop job_sightings (debug history only; jobs is untouched).

    Dropping the table drops its indexes and foreign key with it. Dropping the
    indexes one by one first fails on MySQL: ix_job_sightings_job_pk backs the FK.
    """
    op.drop_table("job_sightings")
