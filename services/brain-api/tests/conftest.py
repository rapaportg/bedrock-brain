"""
Test configuration.

Sets environment variables before any app module is imported so that:
  - settings.environment = "test"
  - No real DB/Redis/S3 connection is attempted at import time
  - FastAPI dependency overrides handle auth + DB in each test
"""

import os
from unittest.mock import patch

import pytest

# Must be set before importing app modules
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("OIDC_ISSUER_URL", "http://localhost:8080/realms/bedrock")
os.environ.setdefault("OIDC_JWKS_URL", "http://localhost:8080/realms/bedrock/protocol/openid-connect/certs")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test")


@pytest.fixture(autouse=True)
def _no_s3(monkeypatch):
    """Prevent any S3 calls during tests — including the startup lifespan."""
    with patch("app.core.s3.ensure_bucket_exists", return_value=None), \
         patch("app.core.s3._client", return_value=None):
        yield
