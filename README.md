# JobScraper API (Poetry + FastAPI + MySQL + Alembic)

A FastAPI microservice that scrapes job listings using [**JobSpy**](https://github.com/speedyapply/JobSpy), persists them in MySQL, and exposes a REST API for querying.  
Now powered by **Poetry** for dependency and environment management.

---

## 🚀 Features
- POST `/scrape` → Run job scraping and persist results
- GET `/jobs` → Query stored job postings with filters & pagination
- GET `/jobs/{id}` → Fetch individual job
- Logging (Loguru)
- Alembic migrations
- MySQL database
- Poetry-based dependency management
- Docker & Docker Compose support

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
```

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


