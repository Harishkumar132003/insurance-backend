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
    # Stronger model used ONLY for SQL generation (the issql path in
    # nl_sql_service). MUST be a model your OpenAI project has access to — e.g.
    # openai:gpt-4o, openai:gpt-4o-mini. Reasoning models (o3-mini, o1) need
    # explicit project access, else the API returns 403 model_not_found.
    AI_SQL_MODEL: str = "openai:o3-mini"
    # Separate reporting DB (a snapshot copy) used ONLY to build table/schema
    # context for the public /ai/intent endpoint. Introspected read-only; no data
    # is returned from it. See cube/*.yml for the semantic "use" descriptions.
    AIAGENT_DATABASE_URL: str = "postgresql+psycopg2://admin:admin123@localhost:5432/aiagent"
    # Cube instance used by /ai/intent to fetch /meta and build the Cube query.
    # In dev mode /meta needs no token; set CUBE_API_SECRET to sign one otherwise.
    CUBE_API_URL: str = "http://localhost:4000"
    CUBE_API_SECRET: str = ""
    # Cube SQL API (Postgres wire protocol) — used by the NL->Cube SQL pipeline to
    # execute generated SQL against the semantic layer. Enable on Cube with
    # CUBEJS_PG_SQL_PORT / CUBEJS_SQL_USER / CUBEJS_SQL_PASSWORD.
    CUBE_SQL_HOST: str = "localhost"
    CUBE_SQL_PORT: int = 15432
    CUBE_SQL_USER: str = "cube"
    CUBE_SQL_PASSWORD: str = "cubeSql2026"
    CUBE_SQL_DB: str = "cube"
    # Qdrant semantic retrieval of relevant cube members for the query-gen step.
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "cube_metadata_openai"
    EMBED_MODEL: str = "text-embedding-3-small"
    CUBE_RETRIEVAL_TOPK: int = 20
    # Only use Qdrant top-k when the scoped menu is LARGER than this many members;
    # below it, send the full menu (more reliable at small scale). Set 0 to always
    # use retrieval, or a very large number to effectively disable it.
    CUBE_RETRIEVAL_MIN_MEMBERS: int = 0
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
