from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import Optional
from app.config import get_settings
from app.db import get_db
from app.schemas import JobOut, ScrapeRequest, JobsQuery
from app.crud import upsert_jobs, list_jobs, get_job
from app.scraper import run_scrape
from app.logging_config import logger

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="API to scrape and fetch job postings using jobspy and persist them to MySQL.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scrape", response_model=dict)
def scrape_jobs_endpoint(payload: ScrapeRequest, db: Session = Depends(get_db)):
    logger.bind(event="scrape.start").debug({"payload": payload.model_dump()})
    try:
        records = run_scrape(payload.model_dump())
        inserted = upsert_jobs(db, records)
        logger.bind(event="scrape.done").debug({"inserted": inserted, "returned": len(records)})
        return {"inserted": inserted, "returned": len(records)}
    except Exception as e:
        logger.exception("Scrape failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs", response_model=dict)
def get_jobs(
    site_name: Optional[str] = None,
    search_term: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    params = JobsQuery(
        site_name=site_name,
        search_term=search_term,
        location=location,
        company=company,
        q=q,
        limit=limit,
        offset=offset,
    )
    total, items = list_jobs(db, params)
    return {
        "total": total,
        "count": len(items),
        "items": [JobOut.model_validate(i).model_dump() for i in items],
    }


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job_by_id(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)
