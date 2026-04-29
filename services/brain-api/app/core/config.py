from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 60

    # Postgres (via PgBouncer)
    postgres_host: str = "pgbouncer"
    postgres_port: int = 6432
    postgres_db: str = "bedrock"
    postgres_user: str = "bedrock"
    postgres_password: str = "changeme"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # S3 / Nutanix Objects
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_name: str = "bedrock-brain"
    s3_region: str = "us-east-1"

    # OIDC (Keycloak dev / Okta prod — same interface)
    oidc_issuer_url: str = "http://keycloak:8080/realms/bedrock"
    oidc_jwks_url: str = "http://keycloak:8080/realms/bedrock/protocol/openid-connect/certs"
    oidc_audience: str = "brain-api"


settings = Settings()
