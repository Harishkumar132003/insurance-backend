from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    # Read-only, RLS-scoped connection used exclusively by the AI query agent.
    # Same database as DATABASE_URL but logs in as `oasys_ai_ro`
    # (see scripts/ai_readonly_role.sql). Falls back to DATABASE_URL if unset,
    # but production MUST set this to the read-only role.
    DATABASE_URL_READONLY: str = ""
    # Model used by the natural-language query agent (LangChain init_chat_model
    # "provider:model" form). Reuses OPENAI_API_KEY.
    AI_QUERY_MODEL: str = "openai:gpt-4o-mini"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-this-to-a-secure-random-string"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    OPENAI_API_KEY: str = ""
    EMAIL_ADDRESS: str = ""
    EMAIL_APP_PASSWORD: str = ""
    UPLOAD_DIR: str = "uploads"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
