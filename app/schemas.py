from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class JobBase(BaseModel):
    site_name: str
    search_term: str
    job_title: str
    company: str
    location: str
    job_url: str

    # New fields from scraper
    job_type: Optional[str] = None
    job_level: Optional[str] = None
    emails: Optional[str] = None  # stored as string, e.g. "hr@example.com, jobs@example.com"
    company_industry: Optional[str] = None
    company_url: Optional[str] = None
    job_id: Optional[str] = None  # external job ID

    description: Optional[str] = None
    date_posted: Optional[datetime] = None
    salary: Optional[str] = None

    # New boolean flags
    is_remote: bool = False
    applied: bool = False


class JobOut(JobBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ScrapeRequest(BaseModel):
    site_name: List[str] = Field(
        default_factory=lambda: ["indeed", "linkedin", "google"],
        example=["indeed", "linkedin"],
    )
    search_term: str = "software engineer"
    google_search_term: Optional[str] = (
        "software engineer jobs near Berlin Germany since yesterday"
    )
    location: str = "Berlin"
    results_wanted: int = 20
    hours_old: int = 72
    country_indeed: Optional[str] = "Germany"
    linkedin_fetch_description: Optional[bool] = True


class JobsQuery(BaseModel):
    site_name: Optional[str] = None
    search_term: Optional[str] = None
    location: Optional[str] = None
    company: Optional[str] = None
    q: Optional[str] = None

    created_after: Optional[datetime] = Field(
        default=datetime(2025, 11, 6, 0, 0, 0),
        description="Return only jobs created after this timestamp (ISO 8601). Defaults to today at midnight.",
        example="2025-11-06T00:00:00Z"
    )

    limit: int = 20
    offset: int = 0
