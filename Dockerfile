FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg build-essential nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY remotion-renderer/package*.json ./remotion-renderer/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && cd remotion-renderer \
    && npm ci

COPY remotion-renderer ./remotion-renderer
COPY youtube-uploader ./youtube-uploader

EXPOSE 8000

CMD ["pleopod-api"]
