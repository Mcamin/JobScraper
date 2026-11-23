from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, func, Integer, Boolean, ForeignKey


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    # Internal DB primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Scraper fields
    site_name: Mapped[str] = mapped_column(String(64), index=True)
    search_term: Mapped[str] = mapped_column(String(255), index=True)
    job_title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str | None] = mapped_column(String(512), index=True, nullable=True)
    location: Mapped[str] = mapped_column(String(255), index=True)
    job_url: Mapped[str] = mapped_column(Text, unique=True)

    # New scraper attributes
    job_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    job_level: Mapped[str | None] = mapped_column(String(128), nullable=True)
    emails: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated list
    company_industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # external job ref (not PK)

    # Existing optional fields
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_posted: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    salary: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Boolean flags
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class JobSighting(Base):
    """One row each time a scrape returns a job that is already stored.

    Written only when a /scrape request sets ``debug_duplicates=true``. It is the
    "last seen" history the ``jobs`` table lacks: it shows when a stored job came
    back, from which search, and why (see ``crud.classify_duplicate``). Nothing
    else reads it; it never changes ``jobs``.
    """

    __tablename__ = "job_sightings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    seen_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), index=True)

    # The search that returned the job again
    site_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_term: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hours_old: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Posting date as reported now vs. what was stored on first scrape
    scraped_date_posted: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    stored_date_posted: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    # Snapshot of the stored job at the time of the sighting
    first_scraped_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # reposted | outside_window | seen_again_in_window | no_posting_date
    reason: Mapped[str] = mapped_column(String(32), index=True)
