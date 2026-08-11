from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List


class JobBase(BaseModel):
    site_name: str
    search_term: str
    job_title: str
    location: str
    job_url: str

    # New fields from scraper
    job_type: Optional[str] = None
    job_level: Optional[str] = None
    company: Optional[str] = None
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

    model_config = ConfigDict(from_attributes=True)


class ScrapeRequest(BaseModel):
    site_name: List[str] = Field(
        default_factory=lambda: ["indeed", "linkedin", "google"],
        json_schema_extra={"example": ["indeed", "linkedin"]},
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
    # Scrape-time filter for jobspy.scrape_jobs() ONLY (does not filter the DB):
    #   True         -> remote-only (jobspy filters at source, e.g. LinkedIn f_WT=2)
    #   None / False -> no filter (returns remote + on-site + unlabeled)
    # jobspy has no on-site-only mode, so False behaves identically to None here.
    is_remote: Optional[bool] = None
    # Response mode (does NOT mutate linkedin_fetch_description):
    #   False -> sync: wait for the full scrape (incl. LinkedIn descriptions) then return.
    #   True  -> return the listing summary immediately; if linkedin_fetch_description
    #            is also True, LinkedIn descriptions are fetched afterwards in the
    #            background. If it is False, no descriptions are fetched (summary only).
    background: bool = False


class JobsQuery(BaseModel):
    site_name: Optional[str] = None
    search_term: Optional[str] = None
    location: Optional[str] = None
    company: Optional[str] = None
    q: Optional[str] = None
    applied: Optional[bool] = Field(
        default=None,
        description="Filter by application status (true = applied, false = not applied).",
        json_schema_extra={"example": True},
    )
    created_after: Optional[datetime] = Field(
        default=datetime(2025, 11, 6, 0, 0, 0),
        description="Return only jobs created after this timestamp (ISO 8601). Defaults to today at midnight.",
        json_schema_extra={"example": "2025-11-06T00:00:00Z"},
    )

    limit: int = 20
    offset: int = 0
