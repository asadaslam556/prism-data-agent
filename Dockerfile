# One container running the whole app: the React build is served by FastAPI
# alongside the API, so there is no second service and no CORS to configure.
# Listens on $PORT when the host sets one, 7860 otherwise. Render, Cloud Run
# and Fly all assign the port at runtime; a hardcoded one means traffic
# arrives at a port nothing is bound to and the deploy fails health checks.
#
# Local check before pushing:
#   docker build -t prism .
#   docker run --rm -p 7860:7860 --env-file backend/.env prism

# ---- stage 1: build the frontend -----------------------------------------
FROM node:20-slim AS frontend

WORKDIR /build

# Copy the manifests first so this layer only rebuilds when deps change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# VITE_API_BASE stays empty on purpose: same origin, so /api resolves itself.
RUN npm run build


# ---- stage 2: python runtime ---------------------------------------------
FROM python:3.12-slim

# Most PaaS hosts run the container as uid 1000. Create that user up front so
# pip, matplotlib and everything else has a home directory it can write to.
RUN useradd --create-home --uid 1000 appuser
USER appuser

ENV HOME=/home/appuser \
    PATH=/home/appuser/.local/bin:$PATH \
    MPLCONFIGDIR=/home/appuser/.cache/matplotlib \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /home/appuser/app

COPY --chown=appuser:appuser backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=appuser:appuser backend/app ./app
COPY --chown=appuser:appuser backend/data ./data
COPY --from=frontend --chown=appuser:appuser /build/dist ./static

# /api/connect dials arbitrary database URLs. Harmless locally, an SSRF vector
# once the container is reachable from a network. Sample and CSV upload stay on.
ENV ENABLE_DB_CONNECT=false

EXPOSE 7860
# Shell form on purpose: exec form would pass the literal string "$PORT".
# `exec` hands PID 1 to uvicorn once the shell has expanded it, so the stop
# signal on a redeploy reaches uvicorn and it shuts down cleanly.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}