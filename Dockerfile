FROM python:3.12-slim-bullseye AS builder

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY src /app/src
COPY setup.py /app/setup.py
COPY __version__.py /app/__version__.py
COPY README.md /app/README.md

RUN python -m venv /app/venv && \
    . /app/venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e .

FROM python:3.12-slim-bullseye

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app /app

RUN useradd -m -d /app appuser && \
    chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/synced_activities"]

CMD ["tp-sync", "sync", "--daemon"]
