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
    # Public origin of THIS backend, e.g. https://oasys-insurance.wizzgeeks.com/api
    # Set it to hand OpenAI a URL for case-sheet page images instead of inlining
    # them as base64. OpenAI's servers fetch the URL themselves, so it must be
    # reachable from the public internet — leave it empty in local development
    # (localhost is not reachable from outside) and the base64 path is used.
    PUBLIC_BASE_URL: str = ""
    # How long a signed case-sheet image link stays valid. Long enough for the
    # extraction call to fetch it, short enough that a leaked link is dead.
    CASE_SHEET_LINK_TTL_SECONDS: int = 900

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
