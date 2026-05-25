"""Central configuration. Everything is overridable via environment variables
so the same code runs identically on a laptop, in CI, or in a container."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env file if present (no-op in production where real env vars are set).
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    # --- Storage locations -------------------------------------------------
    UPLOAD_DIR: Path = Path(
        os.getenv("IDP_UPLOAD_DIR", str(BASE_DIR / "storage" / "uploads"))
    )
    QUARANTINE_DIR: Path = Path(
        os.getenv("IDP_QUARANTINE_DIR", str(BASE_DIR / "storage" / "quarantine"))
    )

    # --- File validation rules --------------------------------------------
    MAX_FILE_SIZE_MB: float = float(os.getenv("IDP_MAX_FILE_SIZE_MB", "10"))
    MAX_FILE_SIZE_BYTES: int = int(MAX_FILE_SIZE_MB * 1024 * 1024)
    # Anything smaller than this is treated as empty / corrupt.
    MIN_FILE_SIZE_BYTES: int = int(os.getenv("IDP_MIN_FILE_SIZE_BYTES", "100"))
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

    # --- Logging -----------------------------------------------------------
    LOG_LEVEL: str = os.getenv("IDP_LOG_LEVEL", "INFO").upper()
    LOG_DIR: Path = Path(os.getenv("IDP_LOG_DIR", str(BASE_DIR / "logs")))

    # --- AI extraction (OpenAI) -------------------------------------------
    # Loaded from .env. The model name is config, never hardcoded, so it can
    # be swapped (e.g. to a newer model) without touching the code.
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


settings = Settings()
