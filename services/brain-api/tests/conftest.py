"""
Test configuration.

Sets environment variables before any app module is imported so that:
  - settings.environment = "test"
  - No real DB/Redis/S3 connection is attempted at import time
  - FastAPI dependency overrides handle auth + DB in each test

The _no_external_calls fixture (autouse) blocks all real S3 operations and
link-sync calls so every test is fully self-contained.
"""

import os
from unittest.mock import AsyncMock, patch

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
def _no_external_calls():
    """
    Block all real S3 I/O and wikilink sync for every test.

    Patches the names as imported in notes.py (where they are used) so that
    tests which want to assert on specific calls can inspect the mocks via
    their own patch() context managers, which take precedence over these.
    """
    with (
        patch("app.core.s3.ensure_bucket_exists", new_callable=AsyncMock),
        patch("app.api.v1.notes.put_note", new_callable=AsyncMock, return_value="testhash"),
        patch("app.api.v1.notes.get_note", new_callable=AsyncMock, return_value="# test content"),
        patch("app.api.v1.notes.delete_note", new_callable=AsyncMock),
        patch("app.api.v1.notes.sync_note_links", new_callable=AsyncMock),
    ):
        yield
