"""Config central via env (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# versatile foi aposentado em 08/2026 — default novo:
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-specdec")

MY_PHONE = os.getenv("MY_PHONE", "244900000000").strip()
WHATSAPP_DB = os.getenv("WHATSAPP_DB", "./whatsapp.db")
WHATSAPP_NAME = os.getenv("WHATSAPP_NAME", "ai_news_bot")

TIMEZONE = os.getenv("TIMEZONE", "Africa/Luanda")
DIGEST_HOURS = os.getenv("DIGEST_HOURS", "8,13,19,23")

SCORE_SEND_NOW = int(os.getenv("SCORE_SEND_NOW", "8"))
SCORE_DIGEST_MIN = int(os.getenv("SCORE_DIGEST_MIN", "5"))
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", "15"))
MAX_DIGEST_ITEMS = int(os.getenv("MAX_DIGEST_ITEMS", "5"))

SEEN_FILE = "./seen_ids.json"

OFFICIAL_SOURCES = {"anthropic", "openai", "groq"}
