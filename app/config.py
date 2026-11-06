import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    PAYPAL_CLIENT_ID: str = os.getenv("PAYPAL_CLIENT_ID", "")
    PAYPAL_SECRET: str = os.getenv("PAYPAL_SECRET", "")
    PAYPAL_BASE_URL: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    PAYPAL_WEBHOOK_ID: str = os.getenv("PAYPAL_WEBHOOK_ID", "")

    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_BASE_URL: Optional[str] = os.getenv("LLM_BASE_URL") or None
    LLM_INCLUDE_REASONING: bool = os.getenv("LLM_INCLUDE_REASONING", "false").lower() in ("true", "1", "yes")
    LLM_REASONING_EFFORT: Optional[str] = os.getenv("LLM_REASONING_EFFORT", "low")

    DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "paychase.db"))
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    CHASER_INTERVAL_SECONDS: int = int(os.getenv("CHASER_INTERVAL_SECONDS", "60"))
    PORT: int = int(os.getenv("PORT", "8000"))

    # Security & Rate Limiting
    DEV_ADMIN_TOKEN: Optional[str] = os.getenv("DEV_ADMIN_TOKEN") or None
    CHAT_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "20"))


settings = Settings()
