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
    version="1.0.0",
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

    try:
        if not payload.background:
            # ---- SYNC (unchanged behaviour) ------------------------------
            records = run_scrape(payload.model_dump())

            invalid_records = [r for r in records if not r.get("company")]
            if invalid_records:
                logger.warning(
                    f"Skipping {len(invalid_records)} records missing 'company' field",
                    extra={"examples": invalid_records[:3]},
                )
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

        invalid_records = [r for r in records if not r.get("company")]
        if invalid_records:
            logger.warning(
                f"Skipping {len(invalid_records)} records missing 'company' field",
                extra={"examples": invalid_records[:3]},
            )
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
