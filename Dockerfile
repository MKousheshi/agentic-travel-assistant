# Pinned to a specific digest (currently resolves to Python 3.12.12) so the
# builder's interpreter version is reproducible and can be kept in sync with
# the runtime stage's python:3.12.12-slim-bookworm tag below.
FROM ghcr.io/astral-sh/uv@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src/ src/
COPY README.md chainlit.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.12.12-slim-bookworm AS runtime

ARG UID=1000
ARG GID=1000

RUN groupadd --gid "${GID}" app \
    && useradd --uid "${UID}" --gid "${GID}" --create-home --shell /usr/sbin/nologin app

COPY --from=builder --chown=app:app /app /app

WORKDIR /app

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8000 8001

CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
