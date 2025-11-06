from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, func, Integer, Boolean


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
    company: Mapped[str] = mapped_column(String(512), index=True)
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
