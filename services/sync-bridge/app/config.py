from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sync_vault_path: str = "/vault"
    sync_api_url: str = "http://brain-api:8000"
    sync_agent_token: str = "sync-bridge-dev-token"
    sync_poll_interval_seconds: int = 5


settings = Settings()
