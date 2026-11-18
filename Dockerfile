FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.14-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint
RUN groupadd --gid 10001 adrobot \
    && useradd --uid 10001 --gid adrobot --no-create-home adrobot \
    && mkdir /data && chown adrobot:adrobot /data \
    && chmod +x /usr/local/bin/backend-entrypoint
USER adrobot
EXPOSE 8000
ENTRYPOINT ["backend-entrypoint"]
CMD ["uvicorn", "adrobot.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
