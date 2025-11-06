# 🧠 JobScraper API

[![Build & Push](https://github.com/Mcamin/JobScraper/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/madtomy/JobScraper/actions/workflows/docker-publish.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/madtomy/jobscraper-api.svg)](https://hub.docker.com/r/madtomy/jobscraper-api)
[![Image Size](https://img.shields.io/docker/image-size/madtomy/jobscraper-api/latest)](https://hub.docker.com/r/madtomy/jobscraper-api)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Mcamin/JobScraper/blob/main/LICENSE)

A **FastAPI-based microservice** for scraping and storing job listings from major job platforms like **Indeed**, **LinkedIn**, **ZipRecruiter**, and **Google Jobs**.

---

## 🚀 Quick Start

Run directly from Docker Hub:

```bash
docker run -d \
  --name jobscraper-api \
  -p 8000:8000 \
  -e DB_HOST=192.168.178.3 \
  -e DB_PORT=3306 \
  -e DB_USER=jobs \
  -e DB_PASSWORD=jobs_Pw! \
  -e DB_NAME=jobsdb \
  -e LOG_LEVEL=info \
  -e LOG_JSON=true \
  madtomy/jobscraper-api:latest
```

Access Swagger UI at:
👉 [http://localhost:8000/docs](http://localhost:8000/docs)

---

## ⚙️ Environment Variables

| Variable               | Description                                         | Default  |
| ---------------------- | --------------------------------------------------- | -------- |
| `APP_PORT`             | Application port                                    | `8000`   |
| `LOG_LEVEL`            | Logging level (`debug`, `info`, `warning`, `error`) | `info`   |
| `LOG_JSON`             | Output structured JSON logs                         | `true`   |
| `DB_HOST`              | MySQL database host                                 | –        |
| `DB_PORT`              | MySQL port                                          | `3306`   |
| `DB_USER`              | MySQL username                                      | –        |
| `DB_PASSWORD`          | MySQL password                                      | –        |
| `DB_NAME`              | Database name                                       | `jobsdb` |
| `DB_POOL_SIZE`         | SQLAlchemy pool size                                | `10`     |
| `DB_POOL_MAX_OVERFLOW` | Connection overflow limit                           | `20`     |

---

## 🧩 Features

* 🔍 Multi-source job scraping
* 🗄️ Persistent MySQL storage (SQLAlchemy ORM)
* 📘 Auto-generated Swagger UI (`/docs`)
* ⚙️ Database migrations (Alembic)
* 🧾 Structured JSON logging (Loguru)
* 🐳 Fully containerized (Docker & Compose support)

---

## 🧱 Example Docker Compose

```yaml
version: "3.9"

services:
  api:
    image: madtomy/jobscraper-api:latest
    container_name: jobscraper-api
    ports:
      - "8000:8000"
    environment:
      APP_ENV: production
      DB_HOST: 192.168.178.3
      DB_PORT: 3306
      DB_USER: jobs
      DB_PASSWORD: "jobs_Pw!"
      DB_NAME: jobsdb
      LOG_JSON: "true"
    restart: unless-stopped
```

Start it:

```bash
docker compose up -d
```

---

## 🧠 Example API Usage

### `POST /scrape`

Trigger a new scraping task:

```json
{
  "site_name": ["indeed", "linkedin", "google"],
  "search_term": "software engineer",
  "google_search_term": "software engineer jobs near Berlin Germany since yesterday",
  "location": "Berlin",
  "results_wanted": 20,
  "hours_old": 72,
  "country_indeed": "Germany",
  "linkedin_fetch_description": true
}
```

---

## 🧾 License

Released under the **MIT License**
© 2025 [Madev](https://github.com/Mcamin)