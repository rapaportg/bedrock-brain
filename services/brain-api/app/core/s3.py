"""
S3 / Nutanix Objects client.

Uses boto3 with a configurable endpoint_url so the same code works against:
  - MinIO      (local dev)
  - Nutanix Objects (staging / prod)
  - AWS S3     (if ever needed)

Key prefix structure:
  private/{user_id}/{note_id}.md
  teams/{team_id}/{note_id}.md
  org/{note_id}.md
  public/{note_id}.md
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

if TYPE_CHECKING:
    pass


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def build_s3_key(visibility: str, note_id: UUID, owner_id: UUID, team_id: UUID | None = None) -> str:
    if visibility == "private":
        return f"private/{owner_id}/{note_id}.md"
    elif visibility == "team" and team_id:
        return f"teams/{team_id}/{note_id}.md"
    elif visibility == "org":
        return f"org/{note_id}.md"
    else:
        return f"public/{note_id}.md"


def put_note(s3_key: str, content: str) -> str:
    """Upload note content and return its SHA-256 hash."""
    encoded = content.encode("utf-8")
    content_hash = hashlib.sha256(encoded).hexdigest()
    _client().put_object(
        Bucket=settings.s3_bucket_name,
        Key=s3_key,
        Body=encoded,
        ContentType="text/markdown; charset=utf-8",
    )
    return content_hash


def get_note(s3_key: str) -> str:
    """Fetch note content from S3."""
    try:
        response = _client().get_object(Bucket=settings.s3_bucket_name, Key=s3_key)
        return response["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise FileNotFoundError(f"Note not found in S3: {s3_key}")
        raise


def delete_note(s3_key: str) -> None:
    """Delete a note object from S3."""
    _client().delete_object(Bucket=settings.s3_bucket_name, Key=s3_key)


def move_note(old_key: str, new_key: str) -> None:
    """Move (copy + delete) a note to a new key — used when visibility changes."""
    _client().copy_object(
        Bucket=settings.s3_bucket_name,
        CopySource={"Bucket": settings.s3_bucket_name, "Key": old_key},
        Key=new_key,
    )
    _client().delete_object(Bucket=settings.s3_bucket_name, Key=old_key)


def ensure_bucket_exists() -> None:
    """Called at startup to ensure the bucket exists."""
    client = _client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket_name)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket_name)
