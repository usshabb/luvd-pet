# Single image, two roles: the web service and the nightly scraper both run
# from it (see docker-compose.yml). Keeps them on identical code and deps.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/New_York

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn

COPY . .

# State lives on a mounted volume so deploys never wipe first_seen dates,
# subscribers or view counts.
ENV LUVD_DB=/data/dogfinder.db
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=8s --start-period=15s \
  CMD curl -fsS http://127.0.0.1:8000/views || exit 1

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "60", "app:app"]
