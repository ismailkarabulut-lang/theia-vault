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



