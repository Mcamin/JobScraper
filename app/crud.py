from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from app.models import Job
from app.schemas import JobsQuery
from typing import Iterable


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

    # --- Optional: filter by created_at if params has it ------------
    if getattr(params, "created_after", None):
        stmt = stmt.where(Job.created_at >= params.created_after)

    # --- Order and pagination ----------------------------------------
    stmt = stmt.order_by(Job.created_at.desc()).limit(params.limit).offset(params.offset)

    # --- Count total -------------------------------------------------
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt).all()

    return total, items



def get_job(db: Session, job_id: int):
    return db.get(Job, job_id)
