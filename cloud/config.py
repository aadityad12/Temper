"""Shared configuration loaded from .env."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Set CLOUD_OFFLINE=true to run the full pipeline with scripted responses (no API keys needed)
CLOUD_OFFLINE = os.getenv("CLOUD_OFFLINE", "").lower() == "true"

PORT = int(os.getenv("CLOUD_PORT") or os.getenv("PORT", "8001"))

# Public URL for connection block generation (no trailing slash)
HOST_URL = os.getenv("TEMPER_HOST_URL", f"http://localhost:{PORT}").rstrip("/")
