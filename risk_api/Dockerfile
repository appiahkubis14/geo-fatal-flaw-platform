FROM python:3.11-slim

# System dependencies (GDAL for geometry operations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev gdal-bin libpq-dev gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
    --timeout=120 \
    --retries=5 \
    -r requirements.txt

COPY . .

# Create non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]