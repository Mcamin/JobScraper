import csv

import numpy as np
import pandas as pd
from typing import List, Dict
from jobspy import scrape_jobs
from app.logging_config import logger
from app.config import get_settings

settings = get_settings()

COLMAP = {
    "id": "job_id",
    "site": "site_name",
    "title": "job_title",
    "company": "company",
    "location": "location",
    "job_url": "job_url",
    "job_type": "job_type",
    "job_level": "job_level",
    "emails": "emails",
    "company_industry": "company_industry",
    "company_url": "company_url",
    "description": "description",
    "date_posted": "date_posted",
    "salary_source": "salary",
    "is_remote": "is_remote",
}


def run_scrape(payload: dict) -> List[Dict]:
    log = logger.bind(event="scrape.start", search_term=payload.get("search_term"))
    log.info("Starting job scrape", payload=payload)

    jobs_df = scrape_jobs(
        site_name=payload.get("site_name"),
        search_term=payload.get("search_term"),
        google_search_term=payload.get("google_search_term"),
        location=payload.get("location"),
        results_wanted=payload.get("results_wanted", 20),
        hours_old=payload.get("hours_old", 72),
        country_indeed=payload.get("country_indeed"),
        linkedin_fetch_description=payload.get("linkedin_fetch_description", False),
    )

    count = len(jobs_df)
    logger.bind(event="scrape.success").info(f"Scraped {count} jobs successfully.")

    # -----------------------------
    # FIX #1: if empty, return []
    # -----------------------------
    if jobs_df.empty:
        logger.warning("Scrape returned 0 jobs. Returning empty list.")
        return []

    # Rename columns according to COLMAP
    jobs_df = jobs_df.rename(columns={k: v for k, v in COLMAP.items() if k in jobs_df.columns})

    # Ensure essential columns exist
    for col in ["site_name", "job_title", "company", "location", "job_url"]:
        if col not in jobs_df.columns:
            jobs_df[col] = None

    # Ensure all required downstream columns exist
    REQUIRED_COLS = [
        "site_name", "search_term", "job_title", "company", "location", "job_url",
        "job_type", "job_level", "emails", "company_industry", "company_url",
        "description", "date_posted", "salary", "is_remote", "job_id"
    ]

    # -----------------------------
    # FIX #2: Add any missing columns
    # -----------------------------
    for col in REQUIRED_COLS:
        if col not in jobs_df.columns:
            jobs_df[col] = None

    # Parse date_posted if present
    if "date_posted" in jobs_df.columns:
        jobs_df["date_posted"] = pd.to_datetime(jobs_df["date_posted"], errors="coerce")

    # Add search term column
    jobs_df["search_term"] = payload.get("search_term")

    # Debug CSV dump in development
    if settings.APP_ENV.lower() == "dev":
        jobs_df.to_csv(
            "/jobs.csv",
            quoting=csv.QUOTE_NONNUMERIC,
            escapechar="\\",
            index=False
        )
        logger.debug("Saved debug CSV output to jobs.csv")

    # Clean NaNs
    jobs_df.replace({np.nan: None, pd.NaT: None}, inplace=True)
    jobs_df.where(pd.notnull(jobs_df), None, inplace=True)

    # -----------------------------
    # FIX #3: Now it's safe — no KeyError possible
    # -----------------------------
    records = jobs_df[REQUIRED_COLS].to_dict(orient="records")

    return records
