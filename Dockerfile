FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./

ADD https://astral.sh/uv/install.sh /tmp/uv-installer.sh

RUN sh /tmp/uv-installer.sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && rm /tmp/uv-installer.sh \
    && uv pip install --system --no-cache flask gunicorn python-dotenv yt-dlp

COPY app ./app
COPY main.py ./main.py

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 120 main:app"]