# ---- Builder ----
FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

COPY pyproject.toml uv.lock ./

RUN uv sync --no-dev --frozen --no-install-project

COPY main.py ./


# ---- Runtime ----
FROM python:3.12-alpine AS runtime

ARG USER=fastapi \
    GROUP_GID=12345 \
    USER_UID=12345 \
    WORKDIR=/app

WORKDIR $WORKDIR

RUN addgroup --system --gid $GROUP_GID $USER && \
    adduser \
    --system \
    --disabled-password \
    --no-create-home $USER \
    --ingroup $USER \
    --uid $USER_UID \
    $USER && \
    chown -R $USER:$USER $WORKDIR

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app main.py logging.config.json ./

USER $USER

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "main:app"]
