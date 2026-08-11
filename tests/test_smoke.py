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

    total, items = list_jobs(db, JobsQuery(limit=10, created_after=None))

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
