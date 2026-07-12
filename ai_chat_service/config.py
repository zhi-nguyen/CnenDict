import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    GOOGLE_APPLICATION_CREDENTIALS: str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/app/key.json")
    GEMINI_MODEL_NAME: str = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
    MAX_HISTORY_TURNS: int = int(os.environ.get("MAX_HISTORY_TURNS", 10))
    AZURE_SPEECH_KEY: str = os.environ.get("AZURE_SPEECH_STUDIO_KEY")
    AZURE_SPEECH_REGION: str = os.environ.get("AZURE_SPEECH_REGION", "southeastasia")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
