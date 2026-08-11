from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db import get_db, SessionLocal
from app.schemas import JobOut, ScrapeRequest, JobsQuery
from app.crud import (
    upsert_jobs,
    list_jobs,
    get_job,
    mark_job_as_applied,
    list_linkedin_jobs_missing_description,
)
from app.scraper import run_scrape, ScrapeError, run_description_backfill
from app.logging_config import logger

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.1.1",
    description="API to scrape and fetch job postings using jobspy and persist them to MySQL.",
)

# --- CORS ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health Check -------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# --- country_indeed resolution ------------------------------------
# jobspy requires a country for Indeed/Glassdoor scrapes. Resolve it explicitly
# so a missing value fails loudly with a clean 400 instead of blowing up deep
# inside jobspy (previously an unhandled None.strip()).
_COUNTRY_REQUIRED_SITES = {"indeed", "glassdoor"}


def resolve_country_indeed(site_name, requested, fallback):
    """Resolve country_indeed for a scrape request.

    Order: request value > env fallback (COUNTRY_INDEED_FALLBACK) > error.
    Returns the resolved country string, or the (possibly None) request value
    when no Indeed/Glassdoor site is targeted (country is irrelevant there).
    Raises ValueError when a country is required but neither source supplies
    one; the caller maps that to HTTP 400.
    """
    needs_country = any(
        str(s).strip().lower() in _COUNTRY_REQUIRED_SITES for s in (site_name or [])
    )
    if not needs_country:
        return requested or None

    country = (requested or "").strip()
    if country:
        return country

    fb = (fallback or "").strip()
    if fb:
        return fb

    raise ValueError(
        "country_indeed is required when scraping Indeed/Glassdoor. "
        "Pass it in the request, or set the COUNTRY_INDEED_FALLBACK env var."
    )


def log_kept_without_company(records):
    """Company is optional (nullable column). We KEEP rows without one and store
    company=NULL; the downstream selection stage (task #10) decides whether to
    use them. Logs honestly — the old message wrongly said "Skipping" while
    inserting them anyway. Returns the count kept.
    """
    missing = [r for r in records if not r.get("company")]
    if missing:
        logger.bind(
            event="scrape.no_company",
            examples=[r.get("job_url") for r in missing[:3]],
        ).warning(f"Kept {len(missing)} job(s) with no company (stored as NULL)")
    return len(missing)


# --- Scrape and Save ----------------------------------------------
@app.post(
    "/scrape",
    response_model=dict,
    tags=["scrape"],
    summary="Scrape jobs and persist them",
    description=(
        "Sync by default (waits for the full scrape, including LinkedIn descriptions). "
        "Set `background=true` to return the listing summary immediately; when "
        "`linkedin_fetch_description=true` the LinkedIn descriptions are then fetched "
        "in the background and backfilled onto the stored rows."
    ),
)
def scrape_jobs_endpoint(
    payload: ScrapeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    logger.bind(event="scrape.start", background=payload.background).info(
        f"Starting scrape for {payload.search_term}"
    )

    # Resolve country_indeed up front (request > env fallback > 400) so an
    # Indeed/Glassdoor scrape can't fail deep inside jobspy on a missing country.
    try:
        payload.country_indeed = resolve_country_indeed(
            payload.site_name,
            payload.country_indeed,
            get_settings().COUNTRY_INDEED_FALLBACK,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        if not payload.background:
            # ---- SYNC (unchanged behaviour) ------------------------------
            records = run_scrape(payload.model_dump())

            log_kept_without_company(records)
            inserted = upsert_jobs(db, records)

            total, db_items = list_jobs(db, JobsQuery(limit=inserted))
            db_items_payload = [JobOut.model_validate(i).model_dump() for i in db_items]

            logger.bind(event="scrape.done").info(
                f"Scrape complete. Inserted: {inserted}, Returned: {len(records)}"
            )

            return {
                "mode": "sync",
                "search_term": payload.search_term,
                "site_name": payload.site_name,
                "location": payload.location,
                "country_indeed": payload.country_indeed,
                "is_remote": payload.is_remote,
                "inserted": inserted,
                "returned": len(records),
                "scrape_items": jsonable_encoder(records),
                "db_items": db_items_payload,
                "items": db_items_payload,
            }

        # ---- BACKGROUND -------------------------------------------------
        # Fast listing pass for THIS call only: pass an explicit False, do NOT
        # mutate payload.linkedin_fetch_description. The caller's flag is read
        # (below) solely to decide whether to schedule the description backfill.
        fast_payload = {**payload.model_dump(), "linkedin_fetch_description": False}
        records = run_scrape(fast_payload)

        log_kept_without_company(records)
        inserted = upsert_jobs(db, records)

        wants_descriptions = bool(payload.linkedin_fetch_description)
        scrapes_linkedin = any(str(s).lower() == "linkedin" for s in payload.site_name)
        will_backfill = wants_descriptions and scrapes_linkedin
        if will_backfill:
            s = get_settings()
            background_tasks.add_task(
                run_description_backfill,
                window_days=s.DESCRIPTION_BACKFILL_WINDOW_DAYS,
                limit=s.DESCRIPTION_BACKFILL_LIMIT,
                concurrency=s.DESCRIPTION_BACKFILL_CONCURRENCY,
                delay=s.DESCRIPTION_BACKFILL_DELAY_SECONDS,
            )

        scrape_items = jsonable_encoder(records)
        logger.bind(event="scrape.done", background=True, backfill=will_backfill).info(
            f"Background scrape complete. Inserted: {inserted}, Returned: {len(records)}"
        )

        return {
            "mode": "background",
            "search_term": payload.search_term,
            "site_name": payload.site_name,
            "location": payload.location,
            "country_indeed": payload.country_indeed,
            "is_remote": payload.is_remote,
            "inserted": inserted,
            "returned": len(records),
            "descriptions": "pending" if will_backfill else "skipped",
            "scrape_items": scrape_items,
            # keep `items` populated so the n8n "Job Scrape Summary" node
            # (which reads items[0].search_term) keeps working unchanged.
            "items": scrape_items,
        }

    except ScrapeError as e:
        # Upstream scraper (jobspy) failed — not our bug. Already logged with
        # full input context in run_scrape(); surface as 502 so the caller can
        # distinguish it from an internal fault.
        raise HTTPException(status_code=502, detail=str(e))

    except Exception as e:
        logger.exception("Scrape failed")
        raise HTTPException(status_code=500, detail=str(e))


# --- Backfill LinkedIn descriptions (on-demand mop-up) -------------
@app.post(
    "/descriptions/backfill",
    response_model=dict,
    tags=["scrape"],
    summary="Backfill missing LinkedIn descriptions",
    description=(
        "Schedules a background sweep that fetches descriptions for description-less "
        "LinkedIn jobs created within the window. Returns the current candidate count. "
        "`window_days`/`limit` default to the configured env values when omitted."
    ),
)
def backfill_descriptions_endpoint(
    background_tasks: BackgroundTasks,
    window_days: int | None = None,
    limit: int | None = None,
):
    s = get_settings()
    w = window_days if window_days is not None else s.DESCRIPTION_BACKFILL_WINDOW_DAYS
    lim = limit if limit is not None else s.DESCRIPTION_BACKFILL_LIMIT

    db = SessionLocal()
    try:
        candidates = len(list_linkedin_jobs_missing_description(db, w, lim))
    finally:
        db.close()

    background_tasks.add_task(
        run_description_backfill,
        window_days=w,
        limit=lim,
        concurrency=s.DESCRIPTION_BACKFILL_CONCURRENCY,
        delay=s.DESCRIPTION_BACKFILL_DELAY_SECONDS,
    )
    return {"scheduled": True, "candidates": candidates, "window_days": w, "limit": lim}


# --- List Jobs ----------------------------------------------------
@app.get("/jobs", response_model=dict)
def get_jobs(params: JobsQuery = Depends(), db: Session = Depends(get_db)):
    total, items = list_jobs(db, params)
    return {
        "total": total,
        "count": len(items),
        "items": [JobOut.model_validate(i).model_dump() for i in items],
    }


# --- Get Job by ID ------------------------------------------------
@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job_by_id(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)


@app.post("/jobs/{job_id}/apply", response_model=dict)
def mark_job_applied(job_id: int, db: Session = Depends(get_db)):
    try:
        job = mark_job_as_applied(db, job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Decide message depending on state
    if job.applied:
        return {
            "message": "Job marked as applied successfully",
            "job_id": job.id,
        }

    return {"message": "Job already marked as applied", "job_id": job.id}
