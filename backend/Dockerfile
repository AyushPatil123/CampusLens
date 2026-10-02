FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY corpus /corpus
RUN useradd --uid 10001 --create-home campuslens && mkdir /data && chown campuslens /data
USER campuslens
ENV CAMPUSLENS_DB=/data/campuslens.sqlite3
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "20", "--timeout-keep-alive", "5", "--no-access-log"]
