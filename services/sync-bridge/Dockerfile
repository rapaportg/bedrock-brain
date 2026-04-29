FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

COPY . .

# Vault mount point — override in docker-compose or K8s with the actual vault path
VOLUME ["/vault"]

CMD ["python", "-m", "app.main"]
