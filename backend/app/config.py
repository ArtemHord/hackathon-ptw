from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    RECALL_API_KEY: str = ""
    RECALL_BASE_URL: str = "https://eu-central-1.recall.ai"
    OPENAI_API_KEY: str = ""
    OPENAI_CHAT_MODEL: str = ""
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL_ID: str = ""
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    DATABASE_URL: str = ""
    PUBLIC_BASE_URL: str = ""
    DEMO_TOKEN: str = ""
    WEBHOOK_TOKEN: str = ""
    AGENT_NAME: str = "Atlas"  # wake word + bot display name (M6.3)
    CORS_ORIGINS: str = "*"  # comma-separated origins for the app / web client


@lru_cache
def get_settings() -> Settings:
    return Settings()
