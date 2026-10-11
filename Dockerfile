FROM node:22-alpine AS dashboard
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPTIPOOL_DATABASE=/data/optipool.db
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY backend/optipool/ ./backend/optipool/
COPY scripts/backup.py ./scripts/backup.py
RUN pip install --no-cache-dir --no-deps . && useradd -u 10001 -m optipool && mkdir /data && chown optipool:optipool /data
COPY --from=dashboard /ui/dist/ ./frontend/dist/
USER 10001
EXPOSE 8000
CMD ["uvicorn", "optipool.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
