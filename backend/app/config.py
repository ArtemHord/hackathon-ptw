from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def keyterms_for(name: str, extra: str = "") -> list[str]:
    """The wake word, its common openers, then comma-separated extras."""
    more = [t.strip() for t in extra.split(",") if t.strip()]
    return [name, f"Hey {name}", f"Okay {name}", *more]


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
    OWNER_NAME: str = "Artem"  # whose delegate the agent is (bot name, system prompt)
    JIRA_BASE_URL: str = ""  # https://<site>.atlassian.net
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_PROJECT_KEY: str = ""
    JIRA_AUTO_CREATE: str = ""  # truthy "1/true/yes": post-call action items -> Jira issues
    AGENT_TOOLS: str = "true"  # M8.1: in-call tool calling (web_search, KB search, create_doc)
    DEMO_PROFILE: str = "acme"  # M10: acme (stand-up demo) | msp (NovaStore incident war room)
    TRANSCRIPT_PROVIDER: str = "recallai"  # recallai | deepgram (M6.6, decision 28)
    TRANSCRIPT_EXTRA_KEYTERMS: str = ""  # comma-separated aliases appended to the keyterms

    @property
    def transcript_keyterms(self) -> list[str]:
        """Deepgram nova-3 keyterm boost: the wake word, its common openers, then extras."""
        return keyterms_for(self.AGENT_NAME, self.TRANSCRIPT_EXTRA_KEYTERMS)

    CORS_ORIGINS: str = "*"  # comma-separated origins for the app / web client


@lru_cache
def get_settings() -> Settings:
    return Settings()
