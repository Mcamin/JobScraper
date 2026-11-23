from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.models import Job, JobSighting
from app.schemas import JobsQuery
from typing import Iterable, List, Optional
from datetime import date, datetime, timedelta
from app.timeutils import local_now_naive
from app.logging_config import logger


def upsert_jobs(
    db: Session, records: Iterable[dict], duplicates: Optional[list] = None
) -> int:
    """Insert jobs, ignore duplicates by unique job_url.

    Race-safe: each row is inserted inside its own SAVEPOINT and a duplicate
    (unique ``job_url``) is swallowed instead of aborting the whole batch. This
    matters under multiple uvicorn workers, where two concurrent scrapes can
    return the same job_url and both pass a naive check-then-insert (TOCTOU),
    with one then hitting MySQL error 1062. Intra-batch duplicates are also
    pre-filtered via ``seen`` so the same URL in one payload doesn't collide.

    ``duplicates``: optional list. When given, every record whose ``job_url`` was
    already stored BEFORE this call is appended as ``(existing_job_pk, record)``.
    Intra-batch repeats and lost insert races are not reported (they are not
    "seen again" jobs). Inserting behaviour is identical either way.
    """
    inserted = 0
    seen: set[str] = set()
    for r in records:
        url = r.get("job_url")
        if not url or url in seen:
            continue
        seen.add(url)
        # Cheap fast-path: skip rows already committed by an earlier scrape.
        existing_pk = db.execute(select(Job.id).where(Job.job_url == url)).scalar_one_or_none()
        if existing_pk:
            if duplicates is not None:
                duplicates.append((existing_pk, r))
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



# --- Duplicate debugging (debug_duplicates=true on /scrape) -----------------

DUPLICATE_REASONS = ("reposted", "outside_window", "seen_again_in_window", "no_posting_date")


def _to_date(value) -> Optional[date]:
    """Best-effort date from a datetime / pandas Timestamp / date / ISO string; None for NaT/NaN."""
    if value is None or str(value) in ("NaT", "nan", "None", ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _to_datetime(value) -> Optional[datetime]:
    d = _to_date(value)
    if d is None:
        return None
    if isinstance(value, datetime):
        if hasattr(value, "to_pydatetime"):  # pandas Timestamp
            value = value.to_pydatetime()
        return value.replace(tzinfo=None)
    return datetime(d.year, d.month, d.day)


def classify_duplicate(scraped_date_posted, stored_date_posted, hours_old, now: datetime) -> str:
    """Why did a scrape limited to the last ``hours_old`` hours return a job we already have?

    Compared at day precision (job boards report posting DATES):
      - no_posting_date       the board gave no posting date now -> can't tell
      - reposted              posting date now is LATER than the one stored on first
                              scrape -> same job id, date bumped (repost / refresh)
      - outside_window        posting date is older than the search window -> the
                              board's time filter let an old posting through
                              (e.g. promoted listings)
      - seen_again_in_window  posting date unchanged and inside the window -> normal
                              overlap with an earlier scrape (e.g. 09:00 vs 11:00 pass)
    """
    scraped = _to_date(scraped_date_posted)
    if scraped is None:
        return "no_posting_date"
    stored = _to_date(stored_date_posted)
    if stored is not None and scraped > stored:
        return "reposted"
    if hours_old:
        cutoff = (now - timedelta(hours=int(hours_old))).date()
        if scraped < cutoff:
            return "outside_window"
    return "seen_again_in_window"


def record_duplicate_sightings(
    db: Session,
    pairs: list,
    *,
    search_term: Optional[str],
    location: Optional[str],
    hours_old: Optional[int],
    persist: bool = True,
) -> tuple[list[dict], bool]:
    """Describe (and optionally store in ``job_sightings``) jobs a scrape returned again.

    ``pairs`` comes from ``upsert_jobs(..., duplicates=pairs)``. Returns
    ``(items, persisted)``. Never modifies ``jobs``. If the sightings table is
    missing (migration 0004 not applied) the report is still returned with
    ``persisted=False`` instead of failing the scrape.
    """
    if not pairs:
        return [], False
    now = local_now_naive()
    jobs = {
        j.id: j
        for j in db.execute(select(Job).where(Job.id.in_([pk for pk, _ in pairs]))).scalars()
    }
    items: list[dict] = []
    rows: list[JobSighting] = []
    for pk, rec in pairs:
        job = jobs.get(pk)
        if job is None:
            continue
        scraped_dp = _to_datetime(rec.get("date_posted"))
        reason = classify_duplicate(scraped_dp, job.date_posted, hours_old, now)
        first = job.created_at
        items.append(
            {
                "job_pk": job.id,
                "job_url": job.job_url,
                "job_title": job.job_title,
                "company": job.company,
                "site_name": rec.get("site_name") or job.site_name,
                "reason": reason,
                "scraped_date_posted": scraped_dp.date().isoformat() if scraped_dp else None,
                "stored_date_posted": _to_date(job.date_posted).isoformat() if job.date_posted else None,
                "first_scraped_at": first.isoformat(sep=" ") if first else None,
                "days_since_first_scraped": (now - first).days if first else None,
                "first_search_term": job.search_term,
                "this_search_term": search_term,
                "applied": bool(job.applied),
            }
        )
        rows.append(
            JobSighting(
                job_pk=job.id,
                seen_at=now,
                site_name=rec.get("site_name") or job.site_name,
                search_term=search_term,
                location=location,
                hours_old=hours_old,
                scraped_date_posted=scraped_dp,
                stored_date_posted=job.date_posted,
                first_scraped_at=first,
                applied=bool(job.applied),
                reason=reason,
            )
        )

    persisted = False
    if persist and rows:
        try:
            db.add_all(rows)
            db.commit()
            persisted = True
        except Exception as e:  # e.g. table missing before migration 0004
            db.rollback()
            logger.bind(event="duplicates.persist_failed").warning(
                f"Could not store {len(rows)} job sighting(s): {e.__class__.__name__}: {e}"
            )
    return items, persisted


def list_duplicate_sightings(
    db: Session,
    *,
    since: datetime,
    until: Optional[datetime] = None,
    search_term: Optional[str] = None,
    reason: Optional[str] = None,
    applied: Optional[bool] = None,
    limit: int = 200,
) -> list[tuple[JobSighting, Job]]:
    stmt = select(JobSighting, Job).join(Job, Job.id == JobSighting.job_pk).where(
        JobSighting.seen_at >= since
    )
    if until is not None:
        stmt = stmt.where(JobSighting.seen_at < until)
    if search_term:
        stmt = stmt.where(JobSighting.search_term == search_term)
    if reason:
        stmt = stmt.where(JobSighting.reason == reason)
    if applied is not None:
        stmt = stmt.where(JobSighting.applied == applied)
    stmt = stmt.order_by(JobSighting.seen_at.desc(), JobSighting.id.desc()).limit(limit)
    return list(db.execute(stmt).all())


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
