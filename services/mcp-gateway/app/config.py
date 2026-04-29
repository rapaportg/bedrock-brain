from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    mcp_gateway_port: int = 8001
    mcp_brain_api_url: str = "http://brain-api:8000"


settings = Settings()
