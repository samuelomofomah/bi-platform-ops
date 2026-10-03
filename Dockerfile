FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BIOPS_DB=/data/biops.db \
    BIOPS_BACKUP_DIR=/data/backups

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY biops/ biops/
COPY sql/ sql/

RUN useradd --uid 10001 --create-home biops && mkdir /data && chown biops /data
USER biops
VOLUME /data

ENTRYPOINT ["python", "-m", "biops"]
CMD ["health"]
