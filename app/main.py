from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db import get_db
from app.schemas import JobOut, ScrapeRequest, JobsQuery
from app.crud import upsert_jobs, list_jobs, get_job, mark_job_as_applied
from app.scraper import run_scrape
from app.logging_config import logger
from app.models import Job

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
@app.post("/scrape", response_model=dict)
def scrape_jobs_endpoint(payload: ScrapeRequest, db: Session = Depends(get_db)):
    logger.bind(event="scrape.start").info(f"Starting scrape for {payload.search_term}")

    try:
        # Run scraper
        records = run_scrape(payload.model_dump())

        # Filter or log invalid records before insert
        invalid_records = [r for r in records if not r.get("company")]
        if invalid_records:
            logger.warning(
                f"Skipping {len(invalid_records)} records missing 'company' field",
                extra={"examples": invalid_records[:3]},  # show first few
            )
        # Persist to DB
        inserted = upsert_jobs(db, records)

        # Query back the newly inserted jobs (optional)
        total, items = list_jobs(db, JobsQuery(limit=inserted))

        logger.bind(event="scrape.done").info(
            f"Scrape complete. Inserted: {inserted}, Returned: {len(items)}"
        )

        return {
            "inserted": inserted,
            "returned": len(records),
            "items": [JobOut.model_validate(i).model_dump() for i in items],
        }

    except Exception as e:
        logger.exception("Scrape failed")
        raise HTTPException(status_code=500, detail=str(e))


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