import csv
import re
import time
import threading
from types import SimpleNamespace
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from jobspy import scrape_jobs
from app.logging_config import logger
from app.config import get_settings

settings = get_settings()

# Guards against overlapping backfill sweeps (only one sweep at a time; the
# per-sweep ThreadPoolExecutor bounds concurrent LinkedIn fetches).
_BACKFILL_LOCK = threading.Lock()
_LINKEDIN_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")


class ScrapeError(RuntimeError):
    """Raised when the underlying jobspy scrape fails.

    Lets the API layer distinguish an upstream scraper failure (HTTP 502)
    from an internal bug/DB error (HTTP 500), instead of collapsing every
    fault into an opaque 500.
    """


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

    try:
        jobs_df = scrape_jobs(
            site_name=payload.get("site_name"),
            search_term=payload.get("search_term"),
            google_search_term=payload.get("google_search_term"),
            location=payload.get("location"),
            results_wanted=payload.get("results_wanted", 20),
            hours_old=payload.get("hours_old", 72),
            country_indeed=payload.get("country_indeed"),
            linkedin_fetch_description=payload.get("linkedin_fetch_description", False),
            # jobspy's ScraperInput requires a real bool; None (caller omitted it)
            # must collapse to False = "no remote filter" (unchanged default behavior).
            is_remote=bool(payload.get("is_remote")),
        )
    except Exception as e:
        # Log the exact inputs so a failure points at the offending site/term,
        # then surface a typed error the API maps to a clean 502.
        logger.bind(
            event="scrape.error",
            site_name=payload.get("site_name"),
            search_term=payload.get("search_term"),
            location=payload.get("location"),
            results_wanted=payload.get("results_wanted", 20),
        ).exception("jobspy scrape_jobs failed")
        raise ScrapeError(
            f"scrape failed for '{payload.get('search_term')}' "
            f"@ '{payload.get('location')}' "
            f"(sites={payload.get('site_name')}): {e}"
        ) from e

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

    # Company is optional (task #6, policy A): keep company-less jobs, but
    # normalize blank/whitespace to a clean NULL so we never store "" or "   ".
    if "company" in jobs_df.columns:
        jobs_df["company"] = jobs_df["company"].map(
            lambda v: (v.strip() or None) if isinstance(v, str) else v
        )

    # -----------------------------
    # FIX #3: Now it's safe — no KeyError possible
    # -----------------------------
    records = jobs_df[REQUIRED_COLS].to_dict(orient="records")

    return records


# ---------------------------------------------------------------------------
# LinkedIn description backfill (async /scrape background mode)
# ---------------------------------------------------------------------------

def has_description_backfill_support() -> bool:
    """True if jobspy still exposes the private LinkedIn detail fetch we rely on.

    We call jobspy's private ``LinkedIn._get_job_details``; this guard lets a
    jobspy upgrade that removes/renames it fail loudly (covered by a test) instead
    of silently backfilling nothing.
    """
    try:
        from jobspy.linkedin import LinkedIn
        return callable(getattr(LinkedIn, "_get_job_details", None))
    except Exception:
        return False


def _linkedin_job_id(job_url: Optional[str]) -> Optional[str]:
    """Extract the numeric job id from a stored LinkedIn job_url (.../jobs/view/<id>)."""
    if not job_url:
        return None
    m = _LINKEDIN_JOB_ID_RE.search(job_url)
    return m.group(1) if m else None


def _make_linkedin_scraper():
    """A LinkedIn scraper wired just enough to call ``_get_job_details`` standalone.

    ``_get_job_details`` only reads ``scraper_input.description_format``, so a light
    shim suffices (avoids constructing a full ScraperInput).
    """
    from jobspy.linkedin import LinkedIn
    from jobspy.model import DescriptionFormat
    scraper = LinkedIn()
    scraper.scraper_input = SimpleNamespace(description_format=DescriptionFormat.MARKDOWN)
    return scraper


def _fetch_description_for_job(job_id: str) -> Optional[str]:
    """Fetch one LinkedIn description. A fresh scraper per call keeps it thread-safe.

    Isolated as its own function so tests can monkeypatch it (no network).
    """
    scraper = _make_linkedin_scraper()
    details = scraper._get_job_details(job_id) or {}
    return details.get("description")


def run_description_backfill(
    session_factory=None,
    *,
    window_days: int,
    limit: int,
    concurrency: int = 2,
    delay: float = 2.0,
) -> dict:
    """Backfill descriptions for description-less LinkedIn jobs (query-driven).

    Only one sweep runs at a time (``_BACKFILL_LOCK``); within a sweep, up to
    ``concurrency`` LinkedIn detail fetches run concurrently, each preceded by a
    polite ``delay``. Network fetches run in worker threads; DB writes happen on a
    single Session in the calling thread (Sessions are not thread-safe).
    """
    from app.crud import list_linkedin_jobs_missing_description, set_job_description
    if session_factory is None:
        from app.db import SessionLocal
        session_factory = SessionLocal

    if not has_description_backfill_support():
        logger.bind(event="backfill.unsupported").error(
            "jobspy LinkedIn._get_job_details missing — description backfill disabled"
        )
        return {"status": "unsupported", "candidates": 0, "updated": 0}

    if not _BACKFILL_LOCK.acquire(blocking=False):
        logger.bind(event="backfill.skip").info("backfill already running; skipping")
        return {"status": "already_running", "candidates": 0, "updated": 0}

    try:
        db = session_factory()
        try:
            jobs = list_linkedin_jobs_missing_description(db, window_days, limit)
            targets = [(j.id, _linkedin_job_id(j.job_url)) for j in jobs]
        finally:
            db.close()

        candidates = len(targets)
        if not candidates:
            return {"status": "ok", "candidates": 0, "updated": 0}

        def work(item):
            job_pk, job_id = item
            if not job_id:
                return (job_pk, None)
            time.sleep(max(delay, 0))  # polite spacing to avoid LinkedIn 429s
            try:
                return (job_pk, _fetch_description_for_job(job_id))
            except Exception:
                logger.bind(event="backfill.fetch_error", job_pk=job_pk).exception(
                    "description fetch failed"
                )
                return (job_pk, None)

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
            results = list(ex.map(work, targets))

        updated = 0
        db = session_factory()
        try:
            for job_pk, desc in results:
                if desc and set_job_description(db, job_pk, desc):
                    updated += 1
        finally:
            db.close()

        logger.bind(event="backfill.done", candidates=candidates, updated=updated).info(
            f"description backfill: {updated}/{candidates} updated"
        )
        return {"status": "ok", "candidates": candidates, "updated": updated}
    finally:
        _BACKFILL_LOCK.release()
