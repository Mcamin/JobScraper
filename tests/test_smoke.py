from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.crud import list_jobs
from app.db import get_db
from app.models import Base, Job
from app.schemas import JobsQuery

client = TestClient(main_module.app)


def test_health():
    """Basic smoke test to verify the API health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def make_job(**overrides):
    job = {
        "site_name": "linkedin",
        "search_term": "Backend Engineer Python",
        "job_title": "Backend Engineer",
        "company": "Acme",
        "location": "Berlin",
        "job_url": "https://example.test/job",
    }
    job.update(overrides)
    return Job(**job)


def test_list_jobs_orders_by_posting_freshness_then_insert_time():
    db = make_session()
    db.add_all(
        [
            make_job(
                job_title="newest inserted but unknown posted date",
                job_url="https://example.test/null-posted",
                date_posted=None,
                created_at=datetime(2026, 7, 7, 12, 0, 0),
            ),
            make_job(
                job_title="older posted date",
                job_url="https://example.test/old-posted",
                date_posted=datetime(2026, 7, 1, 9, 0, 0),
                created_at=datetime(2026, 7, 7, 13, 0, 0),
            ),
            make_job(
                job_title="newer posted date",
                job_url="https://example.test/new-posted",
                date_posted=datetime(2026, 7, 6, 9, 0, 0),
                created_at=datetime(2026, 7, 7, 8, 0, 0),
            ),
        ]
    )
    db.commit()

    total, items = list_jobs(db, JobsQuery(limit=10, all_time=True))

    assert total == 3
    assert [item.job_title for item in items] == [
        "newer posted date",
        "older posted date",
        "newest inserted but unknown posted date",
    ]


def test_scrape_response_includes_metadata_and_separate_scrape_items(monkeypatch):
    db = make_session()
    db.add(
        make_job(
            job_url="https://example.test/duplicate",
            date_posted=datetime(2026, 7, 6, 9, 0, 0),
        )
    )
    db.commit()

    records = [
        {
            "site_name": "linkedin",
            "search_term": "Backend Engineer Python",
            "job_title": "Backend Engineer",
            "company": "Acme",
            "location": "Berlin",
            "job_url": "https://example.test/duplicate",
            "job_type": None,
            "job_level": None,
            "emails": None,
            "company_industry": None,
            "company_url": None,
            "job_id": None,
            "description": None,
            "date_posted": None,
            "salary": None,
            "is_remote": False,
        }
    ]

    def override_db():
        yield db

    monkeypatch.setattr(main_module, "run_scrape", lambda payload: records)
    main_module.app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/scrape",
            json={
                "site_name": ["linkedin"],
                "search_term": "Backend Engineer Python",
                "location": "Berlin",
                "country_indeed": "Germany",
                "is_remote": False,
            },
        )
    finally:
        main_module.app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["search_term"] == "Backend Engineer Python"
    assert body["site_name"] == ["linkedin"]
    assert body["location"] == "Berlin"
    assert body["country_indeed"] == "Germany"
    assert body["is_remote"] is False
    assert body["inserted"] == 0
    assert body["returned"] == 1
    assert body["scrape_items"][0]["job_url"] == "https://example.test/duplicate"
    assert body["db_items"] == []
    assert body["items"] == []


# ---------------------------------------------------------------------------
# Description backfill (async /scrape background mode)
# ---------------------------------------------------------------------------

def test_description_backfill_support_guard():
    """Fails loudly if a jobspy upgrade removes the private LinkedIn detail fetch
    we depend on (LinkedIn._get_job_details)."""
    from app.scraper import has_description_backfill_support

    assert has_description_backfill_support() is True


def _shared_sqlite_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_list_linkedin_jobs_missing_description():
    from datetime import timedelta, timezone
    from app.crud import list_linkedin_jobs_missing_description

    db = make_session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add_all(
        [
            make_job(job_url="https://www.linkedin.com/jobs/view/111",
                     site_name="linkedin", description=None, created_at=now),          # eligible
            make_job(job_url="https://www.linkedin.com/jobs/view/222",
                     site_name="linkedin", description="", created_at=now),            # eligible (empty)
            make_job(job_url="https://www.linkedin.com/jobs/view/333",
                     site_name="linkedin", description="has it", created_at=now),      # has desc -> excluded
            make_job(job_url="https://www.indeed.com/viewjob?jk=444",
                     site_name="indeed", description=None, created_at=now),            # not linkedin -> excluded
            make_job(job_url="https://www.linkedin.com/jobs/view/555",
                     site_name="linkedin", description=None,
                     created_at=now - timedelta(days=10)),                             # too old -> excluded
        ]
    )
    db.commit()

    rows = list_linkedin_jobs_missing_description(db, window_days=3, limit=50)
    assert {r.job_url for r in rows} == {
        "https://www.linkedin.com/jobs/view/111",
        "https://www.linkedin.com/jobs/view/222",
    }


def test_run_description_backfill_updates_rows(monkeypatch):
    from app import scraper as scraper_module
    from app.crud import list_linkedin_jobs_missing_description

    Factory = _shared_sqlite_factory()
    seed = Factory()
    seed.add_all(
        [
            make_job(job_url="https://www.linkedin.com/jobs/view/111",
                     site_name="linkedin", description=None),
            make_job(job_url="https://www.linkedin.com/jobs/view/222",
                     site_name="linkedin", description=None),
        ]
    )
    seed.commit()
    seed.close()

    # No network: canned description per job id, and force the guard True.
    monkeypatch.setattr(scraper_module, "has_description_backfill_support", lambda: True)
    monkeypatch.setattr(
        scraper_module, "_fetch_description_for_job", lambda job_id: f"desc-{job_id}"
    )

    result = scraper_module.run_description_backfill(
        session_factory=Factory, window_days=3, limit=50, concurrency=2, delay=0
    )
    assert result["candidates"] == 2
    assert result["updated"] == 2

    check = Factory()
    try:
        assert list_linkedin_jobs_missing_description(check, 3, 50) == []
        by_id = {j.job_url: j.description for j in check.query(Job).all()}
    finally:
        check.close()
    assert by_id["https://www.linkedin.com/jobs/view/111"] == "desc-111"
    assert by_id["https://www.linkedin.com/jobs/view/222"] == "desc-222"


def _linkedin_listing_record(search_term="Backend Engineer Python",
                             url="https://www.linkedin.com/jobs/view/999"):
    return {
        "site_name": "linkedin", "search_term": search_term,
        "job_title": "Backend Engineer", "company": "Acme", "location": "Berlin",
        "job_url": url, "job_type": None, "job_level": None, "emails": None,
        "company_industry": None, "company_url": None, "job_id": None,
        "description": None, "date_posted": None, "salary": None, "is_remote": False,
    }


def test_scrape_background_schedules_backfill(monkeypatch):
    db = make_session()

    def override_db():
        yield db

    monkeypatch.setattr(main_module, "run_scrape",
                        lambda payload: [_linkedin_listing_record()])
    calls = {}
    monkeypatch.setattr(main_module, "run_description_backfill",
                        lambda **kw: calls.update(kw))
    main_module.app.dependency_overrides[get_db] = override_db
    try:
        response = client.post(
            "/scrape",
            json={"site_name": ["linkedin"], "search_term": "Backend Engineer Python",
                  "location": "Berlin", "background": True,
                  "linkedin_fetch_description": True},
        )
    finally:
        main_module.app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "background"
    assert body["descriptions"] == "pending"
    assert body["returned"] == 1
    # n8n "Job Scrape Summary" reads items[0].search_term — must stay populated.
    assert body["items"][0]["search_term"] == "Backend Engineer Python"
    # BackgroundTasks run after the response; env default window flows through.
    assert calls.get("window_days") == 3


def test_scrape_background_skips_backfill_when_fetch_desc_false(monkeypatch):
    db = make_session()

    def override_db():
        yield db

    monkeypatch.setattr(main_module, "run_scrape",
                        lambda payload: [_linkedin_listing_record()])
    called = {"n": 0}
    monkeypatch.setattr(main_module, "run_description_backfill",
                        lambda **kw: called.__setitem__("n", called["n"] + 1))
    main_module.app.dependency_overrides[get_db] = override_db
    try:
        response = client.post(
            "/scrape",
            json={"site_name": ["linkedin"], "search_term": "X", "location": "Berlin",
                  "background": True, "linkedin_fetch_description": False},
        )
    finally:
        main_module.app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "background"
    assert body["descriptions"] == "skipped"
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# country_indeed resolution (request > env fallback > 400)
# ---------------------------------------------------------------------------

def test_resolve_country_indeed_request_wins():
    from app.main import resolve_country_indeed

    assert resolve_country_indeed(["indeed"], "France", "Germany") == "France"
    # request value is stripped
    assert resolve_country_indeed(["indeed", "linkedin"], "  France  ", None) == "France"


def test_resolve_country_indeed_falls_back_to_env_when_blank():
    from app.main import resolve_country_indeed

    assert resolve_country_indeed(["indeed"], None, "Germany") == "Germany"
    assert resolve_country_indeed(["indeed"], "", "Germany") == "Germany"
    assert resolve_country_indeed(["indeed"], "   ", "  Germany ") == "Germany"


def test_resolve_country_indeed_raises_when_required_and_unresolved():
    import pytest
    from app.main import resolve_country_indeed

    with pytest.raises(ValueError):
        resolve_country_indeed(["indeed"], None, None)
    with pytest.raises(ValueError):
        resolve_country_indeed(["glassdoor"], "", "")


def test_resolve_country_indeed_ignored_without_indeed_or_glassdoor():
    from app.main import resolve_country_indeed

    # No Indeed/Glassdoor -> country irrelevant, never raises.
    assert resolve_country_indeed(["linkedin", "google"], None, None) is None
    assert resolve_country_indeed(["linkedin"], "France", None) == "France"


def test_scrape_indeed_without_country_returns_400(monkeypatch):
    """Indeed requested, no country in request and no env fallback -> clean 400,
    and jobspy is never invoked."""
    db = make_session()

    def override_db():
        yield db

    called = {"n": 0}
    monkeypatch.setattr(
        main_module, "run_scrape",
        lambda payload: called.__setitem__("n", called["n"] + 1) or [],
    )
    # Force no env fallback so the 400 path is deterministic regardless of .env.
    monkeypatch.setattr(
        main_module, "get_settings",
        lambda: type("S", (), {"COUNTRY_INDEED_FALLBACK": None})(),
    )
    main_module.app.dependency_overrides[get_db] = override_db
    try:
        response = client.post(
            "/scrape",
            json={"site_name": ["indeed"], "search_term": "X", "location": "Berlin"},
        )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "country_indeed" in response.json()["detail"]
    assert called["n"] == 0  # never reached the scraper


# ---------------------------------------------------------------------------
# Missing-company handling (policy A: keep + store NULL, honest log)
# ---------------------------------------------------------------------------

def test_scrape_keeps_records_without_company(monkeypatch):
    """A company-less job is KEPT (not skipped) and stored with company=NULL."""
    db = make_session()

    def override_db():
        yield db

    records = [
        {**_linkedin_listing_record(url="https://example.test/no-company"),
         "company": None},
        {**_linkedin_listing_record(url="https://example.test/with-company"),
         "company": "Acme"},
    ]
    monkeypatch.setattr(main_module, "run_scrape", lambda payload: records)
    main_module.app.dependency_overrides[get_db] = override_db
    try:
        response = client.post(
            "/scrape",
            json={"site_name": ["linkedin"], "search_term": "X",
                  "location": "Berlin", "country_indeed": "Germany"},
        )
    finally:
        main_module.app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["inserted"] == 2   # company-less row kept, not dropped
    assert body["returned"] == 2
    stored = {j.job_url: j.company for j in db.query(Job).all()}
    assert stored["https://example.test/no-company"] is None
    assert stored["https://example.test/with-company"] == "Acme"


def test_log_kept_without_company_counts():
    from app.main import log_kept_without_company

    n = log_kept_without_company(
        [
            {"company": None, "job_url": "u1"},
            {"company": "", "job_url": "u2"},
            {"company": "Acme", "job_url": "u3"},
        ]
    )
    assert n == 2


# ---------------------------------------------------------------------------
# created_after rolling-window default (task #1)
# ---------------------------------------------------------------------------

def test_created_after_default_is_rolling_window():
    """Omitted created_after resolves to now(APP_TIMEZONE) - CREATED_AFTER_WINDOW_DAYS,
    computed per request — never the old frozen 2025-11-06.

    Resolution lives in JobsQuery.resolve_created_after() (not a field
    default_factory), so it works through FastAPI's Depends() query-model too."""
    from datetime import datetime, timedelta
    from app.schemas import JobsQuery
    from app.config import get_settings
    from app.timeutils import local_now_naive

    days = get_settings().CREATED_AFTER_WINDOW_DAYS
    now = local_now_naive()  # same frame the resolver uses (Berlin wall-clock)

    resolved = JobsQuery().resolve_created_after()
    assert resolved is not None
    assert resolved > datetime(2026, 1, 1)  # not the stale frozen default
    delta = now - resolved
    assert (
        timedelta(days=days) - timedelta(minutes=1)
        <= delta
        <= timedelta(days=days) + timedelta(minutes=1)
    )


def test_all_time_disables_filter():
    """all_time=true disables the created_after filter (resolves to None)."""
    from app.schemas import JobsQuery

    assert JobsQuery(all_time=True).resolve_created_after() is None
    # all_time overrides an explicit created_after too
    assert JobsQuery(created_after=datetime(2026, 8, 1), all_time=True).resolve_created_after() is None


def test_explicit_created_after_is_used():
    """An explicit created_after wins over the rolling-window default."""
    from app.schemas import JobsQuery

    ts = datetime(2026, 8, 1, 0, 0, 0)
    assert JobsQuery(created_after=ts).resolve_created_after() == ts


def test_jobs_endpoint_default_window_is_not_422():
    """Regression (1.1.2): GET /jobs with NO created_after must NOT 422.

    FastAPI does not invoke a field default_factory for Depends() query-models,
    so the 1.1.1 rolling-window default 422'd on the default path. This test
    exercises the real HTTP query layer that the unit tests missed."""
    from app.timeutils import local_now_naive
    db = make_session()
    # Two jobs: one fresh (inside the rolling window), one ancient (outside).
    fresh_created = local_now_naive()
    db.add_all([
        make_job(job_url="https://example.test/fresh", created_at=fresh_created),
        make_job(job_url="https://example.test/ancient",
                 created_at=datetime(2020, 1, 1, 0, 0, 0)),
    ])
    db.commit()

    def override_db():
        yield db

    main_module.app.dependency_overrides[get_db] = override_db
    try:
        # Default path: omitted created_after -> rolling window, NOT 422.
        r_default = client.get("/jobs")
        # all_time: full history.
        r_all = client.get("/jobs", params={"all_time": "true"})
    finally:
        main_module.app.dependency_overrides.clear()

    assert r_default.status_code == 200, r_default.text
    urls_default = [i["job_url"] for i in r_default.json()["items"]]
    assert "https://example.test/fresh" in urls_default
    assert "https://example.test/ancient" not in urls_default  # window excludes it

    assert r_all.status_code == 200, r_all.text
    urls_all = [i["job_url"] for i in r_all.json()["items"]]
    assert "https://example.test/ancient" in urls_all  # all_time includes it


def test_local_now_naive_uses_configured_timezone():
    """local_now_naive() is APP_TIMEZONE wall-clock (Berlin), not UTC."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from app.timeutils import local_now_naive
    from app.config import get_settings

    tz = ZoneInfo(get_settings().APP_TIMEZONE)
    expected = datetime.now(tz).replace(tzinfo=None)
    got = local_now_naive()
    assert abs((expected - got).total_seconds()) < 5
    # Europe/Berlin is ahead of UTC, so the local wall-clock is >= UTC now.
    assert got >= datetime.now(timezone.utc).replace(tzinfo=None)
