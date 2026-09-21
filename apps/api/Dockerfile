FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY packages/contracts packages/contracts
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --package auspex-api
COPY alembic.ini ./
COPY database database
RUN useradd --system app
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000"]
