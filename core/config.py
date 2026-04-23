"""Ayarlar, paylaşılan istemciler ve yetki kontrolü."""

import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telegram import Update

_env = Path.home() / "theia" / ".env"
load_dotenv(_env if _env.exists() else ".env")

TOKEN     = os.environ["TELEGRAM_TOKEN"]
CHAT_ID   = int(os.environ["CHAT_ID"])
USER_ID   = int(os.environ["USER_ID"])
DB_PATH   = Path.home() / "theia" / "theia.db"
VAULT_DIR = Path.home() / "theia-vault"

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM = (
    "Ben THEIA'yım. Kaptan İsmail'in dijital asistanıyım. "
    "Kısa ve net konuşurum. Türkçe cevap veririm. Kaptanıma saygılıyım."
)
SYSTEM_WEB = SYSTEM + (
    " Web arama sonuçları geldiğinde doğrudan özet ver, "
    "alternatif site önerme. Sonuç yoksa kısa söyle."
)

WEB_TOOLS = [{"type": "web_search_20250305", "name": "web_search"}]


def ok(update: Update) -> bool:
    """Gelen güncellemenin yetkili kullanıcıdan gelip gelmediğini kontrol eder."""
    user = update.effective_user
    if user is None or user.id != USER_ID:
        if user is not None:
            log.warning(
                "Yetkisiz erişim girişimi: user_id=%s username=%s",
                user.id,
                user.username or "?",
            )
        return False
    return True
