FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install package (pyproject.toml based)
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Non-root user
# .garth/ session tokens are stored in the garmin-tokens named volume mounted at /app/.garth
RUN useradd -m -u 1000 garminuser && chown -R garminuser:garminuser /app
USER garminuser

EXPOSE 5555

HEALTHCHECK --interval=60s --timeout=15s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:5555/health || exit 1

CMD ["python", "-m", "garmin_mcp", "--http", "--port", "5555"]
