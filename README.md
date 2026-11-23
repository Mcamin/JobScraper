# JobScraper API

A FastAPI microservice that scrapes job listings using [**JobSpy**](https://github.com/speedyapply/JobSpy), persists them in MySQL, and exposes a REST API for querying.  
Now powered by **Poetry** for dependency and environment management. The jobScraper is used with an N8n workflow 
to automate the job application process.

---

## 🚀 Features
- POST `/scrape` → Run job scraping and persist results (**sync** or **background** mode)
- POST `/descriptions/backfill` → Backfill missing LinkedIn descriptions on demand
- GET `/jobs` → Query stored job postings with filters & pagination
- GET `/jobs/{id}` → Fetch individual job
- GET `/debug/duplicates` → List jobs that scrapes returned again (`debug_duplicates=true`)
- Interactive API docs (Swagger `/docs`, ReDoc `/redoc`)
- Logging (Loguru)
- Alembic migrations
- MySQL database
- Poetry-based dependency management
- Docker & Docker Compose support

---

## 🔀 Scrape modes & LinkedIn description backfill

`POST /scrape` supports two response modes via the `background` flag. It **never mutates**
`linkedin_fetch_description` — that flag is read only to decide whether descriptions are wanted.

| `background` | `linkedin_fetch_description` | Behaviour |
| --- | --- | --- |
| `false` (default) | `false` | **Sync** — wait for the scrape (listings only), then return. |
| `false` | `true` | **Sync** — wait for the full scrape *including* LinkedIn descriptions (slow → risks the caller's timeout). |
| `true` | `false` | Return the listing summary **immediately**. No descriptions fetched. |
| `true` | `true` | Return the listing summary **immediately**, then fetch LinkedIn descriptions **in the background** and backfill them onto the stored rows. |

Why: LinkedIn descriptions are fetched one job at a time (`O(n)`) and can exceed an upstream
client timeout (e.g. n8n's 300 s). Background mode decouples the fast listing response from
the slow description fetch. (Indeed/Google return descriptions inline, so backfill is LinkedIn-only.)

**Backfill is query-driven & self-healing.** The background sweep targets *LinkedIn jobs with
no description created within `DESCRIPTION_BACKFILL_WINDOW_DAYS`*, so if a sweep is interrupted
(crash / restart / 429) those rows stay description-less and are retried by the next sweep.
Only one sweep runs at a time; within a sweep at most `DESCRIPTION_BACKFILL_CONCURRENCY`
fetches run concurrently, each after a polite delay.

On-demand mop-up:

```bash
curl -X POST "http://localhost:8000/descriptions/backfill?window_days=3&limit=50"
# → {"scheduled": true, "candidates": 7, "window_days": 3, "limit": 50}
```

> Implementation note: backfill calls jobspy's private `LinkedIn._get_job_details`. A guard
> test fails loudly if a jobspy upgrade removes it.

---

## 🔍 Duplicate debugging (`debug_duplicates`)

A scrape skips every job whose `job_url` is already stored. To see **which** jobs came back
and **why** a time-limited search (e.g. `hours_old: 24`) returned them, add
`"debug_duplicates": true` to the `/scrape` request. It is report-only: stored jobs are never
changed, and scrapes without the flag behave exactly as before.

With the flag, the response gains:

| Field | Meaning |
|---|---|
| `duplicate_count` | jobs returned by this search that were already stored |
| `duplicate_reasons` | count per reason (below) |
| `duplicates` | one entry per job: link, title, company, posting date now vs. stored, first scraped at, days since, the search that first found it, `applied` |
| `sightings_recorded` | `true` when the entries were written to `job_sightings` |

Each duplicate is also stored in the `job_sightings` table (migration `0004`), so the history
survives the request. List it with `GET /debug/duplicates`:

```bash
curl "http://localhost:8000/debug/duplicates?since=2026-11-23T00:00:00&reason=reposted"
# filters: since (default: last 24 h), until, search_term, reason, applied, limit (≤ 2000)
```

Reasons (compared by posting **date**):

| Reason | Meaning |
|---|---|
| `reposted` | posting date is later than the one stored on first scrape: same job id, date bumped |
| `outside_window` | posting date is older than `hours_old`: the board's time filter let it through |
| `seen_again_in_window` | posting date unchanged and inside the window: normal overlap with an earlier scrape |
| `no_posting_date` | the board returned no posting date |

If the API runs before migration `0004` is applied, the report is still returned with
`sightings_recorded: false`; only the history table is missing.

---

## ⚙️ Local Development (with Poetry)

1. **Install Poetry**
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   export PATH="$HOME/.local/bin:$PATH"
    ```
2. **Install dependencies**

   ```bash
   poetry install
   ```

3. **Run migrations**

   ```bash
   poetry run alembic upgrade head
   ```

4. **Start the API**

   ```bash
   poetry run uvicorn app.main:app --reload
   ```

5. **Visit docs**

   * Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
   * Redoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🐳 Docker Deployment

1. **Build the container**

   ```bash
   docker compose build
   ```

2. **Run**

   ```bash
   docker compose up
   ```

   * API: [http://localhost:8000](http://localhost:8000)
   * MySQL: on port 3306 (default credentials from `.env`)

3. **Apply migrations in container**

   ```bash
   docker compose exec api poetry run alembic upgrade head
   ```

---

## 🧰 Environment Variables (`.env`)

Example:

```env
APP_NAME=JobScraper API
APP_ENV=dev
DB_HOST=db
DB_PORT=3306
DB_USER=jobs
DB_PASSWORD=jobs_pw
DB_NAME=jobsdb

# App timezone — MUST match the DB server timezone (see below).
APP_TIMEZONE=Europe/Berlin

# /jobs default created_after = now(APP_TIMEZONE) minus this many days.
CREATED_AFTER_WINDOW_DAYS=7

# Description backfill (async /scrape background mode) — defaults shown
DESCRIPTION_BACKFILL_WINDOW_DAYS=3
DESCRIPTION_BACKFILL_LIMIT=50
DESCRIPTION_BACKFILL_CONCURRENCY=2
DESCRIPTION_BACKFILL_DELAY_SECONDS=2.0

# Fallback country for Indeed/Glassdoor scrapes (see below). Unset by default.
COUNTRY_INDEED_FALLBACK=Germany
```

### `/jobs` time window (`created_after`) and timezone

`/jobs` returns only jobs created at/after `created_after`. When the caller
omits it, it defaults to a **rolling window** — `now(APP_TIMEZONE) −
CREATED_AFTER_WINDOW_DAYS` (default 7 days), computed **per request** so it never
freezes. Pass `created_after=null` to disable the time filter entirely.

**Timezone matters:** `created_at` is written by the DB (`func.now()`) in the DB
server's *local* timezone (this deployment runs **Europe/Berlin**, not UTC).
Set **`APP_TIMEZONE`** to match the DB server so window cutoffs align with the
stored timestamps; if the DB server ever moves to UTC, set `APP_TIMEZONE=UTC`.

### `country_indeed` resolution (Indeed / Glassdoor)

jobspy requires a country for **Indeed** and **Glassdoor** scrapes. `/scrape`
resolves it in this order:

1. **Request value** — `country_indeed` in the POST body, if non-blank.
2. **Env fallback** — `COUNTRY_INDEED_FALLBACK`, if set to a non-blank value.
3. **Fail loudly** — otherwise the request is rejected with **HTTP 400**
   (jobspy is never called).

`country_indeed` is **ignored** when neither Indeed nor Glassdoor is in
`site_name` (e.g. LinkedIn/Google-only scrapes). Set
`COUNTRY_INDEED_FALLBACK=Germany` in the deployment `.env` to make Germany the
default while still letting individual requests override it; leave it unset to
force every Indeed/Glassdoor request to pass `country_indeed` explicitly.

---

## 🧠 Common Commands

| Task               | Command                                    |
| ------------------ | ------------------------------------------ |
| Add new dependency | `poetry add <package>`                     |
| Add dev dependency | `poetry add --group dev <package>`         |
| Remove dependency  | `poetry remove <package>`                  |
| Run migrations     | `poetry run alembic upgrade head`          |
| Start dev server   | `poetry run uvicorn app.main:app --reload` |
| Run tests          | `poetry run pytest`                        |

---

## 📦 Project Structure

```
app/
├─ main.py
├─ models.py
├─ crud.py
├─ schemas.py
├─ db.py
├─ config.py
├─ scraper.py
docs/
├─ openapi.yaml
migrations/
├─ env.py
├─ versions/
tests/
├─ test_smoke.py
```

---

## 🧩 Alembic Migrations

Alembic is already configured for autogeneration based on `app.models`.

### Generate new migration

```bash
poetry run alembic revision --autogenerate -m "add new columns"
```

### Apply migrations

```bash
poetry run alembic upgrade head
```

In the deployed container (1.2.0 adds `0004_add_job_sightings_table`):

```bash
docker exec <jobscraper-api container> sh -c 'cd /app && PYTHONPATH=/app alembic upgrade head'
```

---

## ✅ Health Check

```bash
curl http://localhost:8000/health
```

Response:

```json
{"status": "ok"}
```

---

## 🧹 Cleaning Up

```bash
docker compose down -v
```

Deletes containers, volumes, and networks.


