from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://sre:sre@localhost:5434/sre"
    redis_url: str = "redis://localhost:6380/0"
    webhook_secret: str = "dev-secret"
    approval_secret: str = "dev-approval-secret"

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"

    alert_stream: str = "sre:alerts"
    dead_stream: str = "sre:dead"
    consumer_group: str = "sre-workers"
    max_critic_loops: int = 2

    @property
    def async_database_url(self) -> str:
        # SQLAlchemy needs the driver name in the URL, psycopg and the MCP servers do not.
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


settings = Settings()
