# src/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "gwei"
    debug: bool = False

    # 数据库
    database_url: str = "postgresql+asyncpg://gwei:gwei@localhost:5432/gwei"
    redis_url: str = "redis://localhost:6379/0"

    # GitHub App
    github_app_id: str = ""
    github_private_key: str = ""
    github_webhook_secret: str = ""

    # LLM
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"

    # SaaS
    deployment_mode: str = "saas"  # saas or self-hosted

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
