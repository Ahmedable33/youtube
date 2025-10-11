# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    git \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements-runtime.txt /app/requirements-runtime.txt
RUN pip install --no-cache-dir -r /app/requirements-runtime.txt

# Copy project
COPY . /app

EXPOSE 8000

# Default command: start orchestrator (monitor, scheduler, queue watcher)
CMD ["python", "start_services.py", "--config", "config/video.docker.yaml", "--sources", "config/sources.yaml", "--log-level", "INFO"]
