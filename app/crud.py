from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from app.models import Job
from app.schemas import JobsQuery
from typing import Iterable, List
from datetime import timedelta
from app.timeutils import local_now_naive


def upsert_jobs(db: Session, records: Iterable[dict]) -> int:
    """Insert jobs, ignore duplicates by unique job_url."""
    inserted = 0
    for r in records:
        if not r.get("job_url"):
            continue
        exists = db.execute(select(Job.id).where(Job.job_url == r["job_url"])).scalar_one_or_none()
        if exists:
            continue
        job = Job(**r)
        db.add(job)
        inserted += 1
    db.commit()
    return inserted



def list_jobs(db: Session, params: JobsQuery):
    stmt = select(Job)

    # --- Filters -----------------------------------------------------
    if params.site_name:
        stmt = stmt.where(Job.site_name == params.site_name)
    if params.search_term:
        stmt = stmt.where(Job.search_term.ilike(f"%{params.search_term}%"))
    if params.location:
        stmt = stmt.where(Job.location.ilike(f"%{params.location}%"))
    if params.company:
        stmt = stmt.where(Job.company.ilike(f"%{params.company}%"))
    if params.q:
        like = f"%{params.q}%"
        stmt = stmt.where(
            or_(
                Job.job_title.ilike(like),
                Job.description.ilike(like),
                Job.company.ilike(like),
            )
        )
    if getattr(params, "applied", None) is not None:
        stmt = stmt.where(Job.applied == params.applied)
    # --- Filter by created_at (rolling-window default resolved here) --
    # JobsQuery.resolve_created_after() applies the rolling window when the
    # param is omitted (FastAPI can't do it via default_factory on a
    # Depends() query-model). Fall back to a raw attr for duck-typed params.
    if hasattr(params, "resolve_created_after"):
        cutoff = params.resolve_created_after()
    else:
        cutoff = getattr(params, "created_after", None)
    if cutoff is not None:
        stmt = stmt.where(Job.created_at >= cutoff)

    # --- Order and pagination ----------------------------------------
    stmt = stmt.order_by(
        Job.date_posted.is_(None).asc(),
        Job.date_posted.desc(),
        Job.created_at.desc(),
    ).limit(params.limit).offset(params.offset)

    # --- Count total -------------------------------------------------
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt).all()

    return total, items

def mark_job_as_applied(db: Session, job_id: int) -> Job:
    """Set a job's 'applied' attribute to True. Raises ValueError if not found."""
    job = db.get(Job, job_id)
    if not job:
        raise ValueError("Job not found")

    if not job.applied:
        job.applied = True
        db.commit()
        db.refresh(job)

    return job

def get_job(db: Session, job_id: int):
    return db.get(Job, job_id)


def list_linkedin_jobs_missing_description(
    db: Session, window_days: int, limit: int
) -> List[Job]:
    """LinkedIn jobs with no description, created within `window_days`, newest first.

    Query-driven so a failed/partial backfill self-heals: rows stay description-less
    and are picked up again by the next sweep (bounded by the window + limit).
    """
    # APP_TIMEZONE wall-clock (Berlin) to match the DB's naive created_at, which
    # MySQL func.now() writes in the server's local timezone (NOT UTC).
    cutoff = local_now_naive() - timedelta(days=window_days)
    stmt = (
        select(Job)
        .where(Job.site_name == "linkedin")
        .where(or_(Job.description.is_(None), Job.description == ""))
        .where(Job.created_at >= cutoff)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def set_job_description(db: Session, job_pk: int, description: str) -> bool:
    """Set a job's description by primary key. Returns True if a row was updated."""
    job = db.get(Job, job_pk)
    if not job:
        return False
    job.description = description
    db.commit()
    return True
