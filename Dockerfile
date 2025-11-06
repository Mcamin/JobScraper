# --- Base image ----------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (for mysqlclient, jobspy, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential default-libmysqlclient-dev pkg-config curl \
    && rm -rf /var/lib/apt/lists/*

# --- Install Poetry ------------------------------------------------------
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# --- Copy project files --------------------------------------------------
COPY pyproject.toml poetry.lock* ./

# --- Install dependencies (no dev deps for smaller image) ----------------
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --no-ansi

# --- Copy source code ----------------------------------------------------
COPY . .

# --- Expose & run --------------------------------------------------------
EXPOSE 8000
CMD ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
