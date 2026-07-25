FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core build-essential nodejs npm \
        # Headless Chromium system libraries for local Remotion rendering
        # (ENABLE_VIDEO_RENDERING=true). Per Remotion's Docker guide.
        libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 \
        libxkbcommon-dev libxfixes3 libxcomposite1 libxdamage1 \
        libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 \
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

# Bake the Chrome Headless Shell into the image so Railway does not download it
# on every render (the filesystem is ephemeral). Safe to keep even when video
# rendering is disabled; it just adds image size.
RUN cd remotion-renderer && npx remotion browser ensure

EXPOSE 8000

CMD ["pleopod-api"]
