FROM python:3.14-slim-bookworm@sha256:e60ad028afdcdd14772a3d46decf0eaf616720f9102aeb4397a2045ff6718c3d
LABEL org.opencontainers.image.source="https://github.com/mochingub-kub/mochilab-openbot-store"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4
WORKDIR /app
COPY requirements.lock .
RUN pip install --disable-pip-version-check --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock
COPY auth.py model.py server.py LICENSE.OpenThai ./
USER 1000:1000
EXPOSE 8080
CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8080","--workers","1","--no-access-log","--no-proxy-headers","--limit-concurrency","16"]
