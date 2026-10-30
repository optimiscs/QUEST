FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/ ./
RUN uv sync --locked --no-dev
COPY --from=frontend /build/dist /app/frontend/dist
RUN useradd --uid 10001 --create-home viewer
USER viewer
ENV VIEWER_FRONTEND_DIR=/app/frontend/dist
EXPOSE 6080
CMD [".venv/bin/uvicorn", "quest_viewer.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "6080"]
