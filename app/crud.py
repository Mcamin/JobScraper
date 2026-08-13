from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.models import Job
from app.schemas import JobsQuery
from typing import Iterable, List
from datetime import timedelta
from app.timeutils import local_now_naive


def upsert_jobs(db: Session, records: Iterable[dict]) -> int:
    """Insert jobs, ignore duplicates by unique job_url.

    Race-safe: each row is inserted inside its own SAVEPOINT and a duplicate
    (unique ``job_url``) is swallowed instead of aborting the whole batch. This
    matters under multiple uvicorn workers, where two concurrent scrapes can
    return the same job_url and both pass a naive check-then-insert (TOCTOU),
    with one then hitting MySQL error 1062. Intra-batch duplicates are also
    pre-filtered via ``seen`` so the same URL in one payload doesn't collide.
    """
    inserted = 0
    seen: set[str] = set()
    for r in records:
        url = r.get("job_url")
        if not url or url in seen:
            continue
        seen.add(url)
        # Cheap fast-path: skip rows already committed by an earlier scrape.
        if db.execute(select(Job.id).where(Job.job_url == url)).scalar_one_or_none():
            continue
        try:
            # SAVEPOINT: on a duplicate-key race the nested tx rolls back on its
            # own, leaving the outer transaction (and prior inserts) intact.
            with db.begin_nested():
                db.add(Job(**r))
                db.flush()
            inserted += 1
        except IntegrityError:
            # Lost the insert race to a concurrent worker — treat as existing.
            continue
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
