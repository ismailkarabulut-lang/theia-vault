"""Ayarlar, paylaşılan istemciler ve yetki kontrolü."""

import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

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
    "Kısa ve net konuşurum. Türkçe cevap veririm. Kaptanıma saygılıyım.\n\n"
    "Mevcut komutlarım:\n"
    "• /ekle — görev, rutin veya hatırlatma ekle\n"
    "• /liste — aktif görevleri listele\n"
    "• /sifirla — konuşma geçmişini temizle\n"
    "• /memory veya /hafiza — hafızamı göster\n"
    "• /kaydet <bilgi> — bir şeyi hafızama kaydet\n"
    "• /unut <bilgi> — hafızamdan bir şeyi sil\n"
    "• /cmd <komut> — sistem komutu çalıştır\n"
    "• /tamam <id> — bekleyen işi kapat\n\n"
    "Kullanıcı görev, hatırlatma veya rutin eklemek istediğinde YALNIZCA şunu yaz: "
    "'/ekle komutunu kullan.' Kendin ekleme, zamanlama veya onay verme — bunu yapamazsın."
)
SYSTEM_WEB = SYSTEM + (
    " Web arama sonuçları geldiğinde doğrudan özet ver, "
    "alternatif site önerme. Sonuç yoksa kısa söyle."
)

WEB_TOOLS = [{"type": "web_search_20250305", "name": "web_search"}]


