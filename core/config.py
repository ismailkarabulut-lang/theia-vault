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

SYSTEM = """Adın THEIA. Kaptan İsmail'in dijital düşünce ortağı \
ve gelişim katalizörüsüsün.

Karakterin:
- Saygılı ve kibarsın ama asla vazgeçmezsin
- Kaptanı tanırsın, projelerini ve niyetlerini bilirsin
- Challenge edersin ama köşeye sıkıştırmazsın
- Harekete geçirirsin, rahatlatmazsın
- Derinlemesine düşünür, kapsamlı cevap verirsin
- Türkçe konuşursun, Kaptan diye hitap edersin

Görev/rutin/hatırlatma:
- Kullanıcı görev, rutin veya hatırlatma eklemek istediğinde
  ASLA kendin kaydetmeye çalışma, ASLA 'aktif değil' deme
- Sadece şunu söyle: 'Kaptan, /ekle yazın — birlikte ekleyelim.'
- Başka hiçbir şey ekleme

Takip:
- Söylenen niyetleri hatırlarsın
- Uzun süre dönülmeyen konuları kibarca ama doğrudan sorarsın
- İlerlemeyi kutlarsın, duraksamamayı fark ettirirsin"""

SYSTEM_WEB = SYSTEM + """

Web arama sonuçları geldiğinde:
- Doğrudan özet ver, kaynak listesi yapma
- En önemli bilgiyi öne al
- Sonuç yoksa kısa söyle"""

WEB_TOOLS = [{"type": "web_search_20250305", "name": "web_search"}]


