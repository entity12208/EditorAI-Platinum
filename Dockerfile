FROM python:3.11-slim

# Install curl for healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY coordinator/ coordinator/
COPY proxy/ proxy/
COPY worker/ worker/

# Create a non-root user
RUN useradd -m -u 1000 ollama && chown -R ollama:ollama /app
USER ollama

# Default command (override in docker-compose.yml)
CMD ["python", "coordinator/server.py"]
