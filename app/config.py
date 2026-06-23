from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
        extra="ignore",
    )

    DATABASE_URL: str
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    LLM_PROVIDER: str = "auto"
    DAILY_CHAT_REQUEST_LIMIT: int = 50
    DAILY_CHAT_TOKEN_LIMIT: int = 100_000
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080
    UPLOAD_DIR: str = "./uploads"
    CHROMA_DIR: str = "./chroma_db"
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def claude_enabled(self) -> bool:
        key = self.ANTHROPIC_API_KEY.strip()
        return bool(key) and key != "your_anthropic_api_key_here"

    @property
    def gemini_enabled(self) -> bool:
        key = self.GEMINI_API_KEY.strip()
        return bool(key) and key not in (
            "your_gemini_api_key_here",
            "your_google_api_key_here",
        )

    @property
    def llm_provider(self) -> str | None:
        provider = self.LLM_PROVIDER.strip().lower()
        if provider == "gemini":
            return "gemini" if self.gemini_enabled else None
        if provider == "anthropic":
            return "anthropic" if self.claude_enabled else None
        if self.gemini_enabled:
            return "gemini"
        if self.claude_enabled:
            return "anthropic"
        return None

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider is not None

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


settings = Settings()
