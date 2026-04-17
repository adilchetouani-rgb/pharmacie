# Geo stack: slim image + system libs so rasterio / rtree / geopandas install reliably.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    g++ \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
# Lower RAM from allocator + BLAS thread pools (important in Docker).
ENV MALLOC_ARENA_MAX=2
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OMP_NUM_THREADS=1
ENV NUMEXPR_MAX_THREADS=1
ENV PYTHONHASHSEED=random

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
