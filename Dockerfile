FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src

ENV PYTHONPATH=/app/src
ENV IPTV_EPG_VERSION=0.11.1
ENV CONFIG_DIR=/config
ENV DATA_DIR=/data
ENV DB_PATH=/db/iptv_epg.db
ENV LOG_DIR=/logs

VOLUME ["/config", "/data", "/db", "/logs"]

EXPOSE 8080

CMD ["uvicorn", "iptv_epg.main:app", "--host", "0.0.0.0", "--port", "8080"]
