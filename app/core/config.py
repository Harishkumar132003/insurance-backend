from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
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
