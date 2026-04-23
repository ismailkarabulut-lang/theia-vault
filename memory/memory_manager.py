"""THEIA Memory Manager — kullanıcı başına kalıcı hafıza sistemi."""

import asyncio
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger("memory")

MEMORY_DIR = Path(__file__).parent / "users"

_EXTRACT_PROMPT = """\
Mevcut memory:
{mevcut_memory}

Son konuşma:
{son_konusma}

Görevin: Bu konuşmadan ileriye dönük gerçekten değerli olan bilgileri belirle.

Eğer güncellenecek bir şey varsa, aşağıdaki formatta SADECE güncellenmiş memory'yi döndür.
Eğer yoksa sadece "NO_UPDATE" yaz.

KURALLAR:
- Maksimum 400 kelime
- Kullanıcının tercihlerini, kararlarını, devam eden projelerini tut
- Geçici veya önemsiz bilgileri ekleme
- Eski ve artık geçerli olmayan bilgileri sil
- Konuşmanın narrative'ini değil, özünü kaydet

FORMAT (bu başlıkları kullan, içerik varsa):
## Tercihler
## Devam Eden Projeler
## Önemli Kararlar
## Teknik Bağlam
## Açık Sorular"""

_HAIKU = "claude-haiku-4-5-20251001"


class MemoryManager:
    """Her kullanıcı için ayrı memory dosyası tutar: memory/users/{user_id}.md"""

    def __init__(self) -> None:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._last_update_count: dict[int, int] = {}

    def _path(self, user_id: int) -> Path:
        return MEMORY_DIR / f"{user_id}.md"

    def load_memory(self, user_id: int) -> str:
        try:
            p = self._path(user_id)
            return p.read_text(encoding="utf-8") if p.exists() else ""
        except OSError as e:
            logger.warning("Memory dosyası okunamadı user=%s: %s", user_id, e)
            return ""

    def save_memory(self, user_id: int, content: str) -> bool:
        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            self._path(user_id).write_text(content.strip(), encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Memory dosyasına yazılamadı user=%s: %s", user_id, e)
            return False

    def should_update_memory(self, user_id: int, conversation_history: list) -> bool:
        total = len(conversation_history)
        last  = self._last_update_count.get(user_id, 0)
        return (total - last) >= 5

    def _mark_updated(self, user_id: int, history_len: int) -> None:
        self._last_update_count[user_id] = history_len

    async def extract_memory_update(
        self, user_id: int, conversation_history: list, claude_client
    ) -> str | None:
        try:
            current = self.load_memory(user_id)
            convo   = "\n".join(
                f"{'Kullanıcı' if m['role'] == 'user' else 'Asistan'}: {m['content']}"
                for m in conversation_history[-20:]
            )
            prompt = _EXTRACT_PROMPT.format(
                mevcut_memory=current or "(boş)",
                son_konusma=convo,
            )
            resp = await asyncio.to_thread(
                claude_client.messages.create,
                model=_HAIKU,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            result = resp.content[0].text.strip()
            self._mark_updated(user_id, len(conversation_history))
            return None if result == "NO_UPDATE" else result
        except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
            logger.warning("Claude API hatası (extract_memory) user=%s: %s", user_id, e)
            return None
        except OSError as e:
            logger.warning("Dosya hatası (extract_memory) user=%s: %s", user_id, e)
            return None
        except Exception:
            logger.exception("Beklenmeyen hata (extract_memory) user=%s", user_id)
            return None

    async def manual_save(
        self, user_id: int, text: str, claude_client
    ) -> str:
        """Kullanıcının kaydetmesini istediği bilgiyi mevcut memory'ye ekler."""
        try:
            current = self.load_memory(user_id)
            prompt  = (
                f"Kullanıcı şunu kaydetmemi istedi: {text}\n\n"
                f"Mevcut memory:\n{current or '(boş)'}\n\n"
                "Mevcut memory'ye bu bilgiyi kısa ve öz ekle veya güncelle. "
                "Sadece GÜNCELLENMİŞ memory'nin tamamını döndür."
            )
            resp = await asyncio.to_thread(
                claude_client.messages.create,
                model=_HAIKU,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            new_mem = resp.content[0].text.strip()
            self.save_memory(user_id, new_mem)
            return "✓ Kaydedildi."
        except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
            logger.warning("Claude API hatası (manual_save) user=%s: %s", user_id, e)
            return "Kaydetme sırasında hata oluştu."
        except OSError as e:
            logger.warning("Dosya hatası (manual_save) user=%s: %s", user_id, e)
            return "Kaydetme sırasında hata oluştu."
        except Exception:
            logger.exception("Beklenmeyen hata (manual_save) user=%s", user_id)
            return "Kaydetme sırasında hata oluştu."

    async def manual_forget(
        self, user_id: int, text: str, claude_client
    ) -> str:
        """Kullanıcının silmesini istediği bilgiyi memory'den kaldırır."""
        try:
            current = self.load_memory(user_id)
            if not current:
                return "Zaten hiçbir şey kaydetmemişim."
            prompt = (
                f"Kullanıcı şunu unutmamı istedi: {text}\n\n"
                f"Mevcut memory:\n{current}\n\n"
                "İlgili bilgiyi memory'den çıkar. "
                "Güncellenmiş memory'yi döndür. "
                "Silinecek bilgi yoksa sadece 'NO_CHANGE' yaz."
            )
            resp = await asyncio.to_thread(
                claude_client.messages.create,
                model=_HAIKU,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            result = resp.content[0].text.strip()
            if result == "NO_CHANGE":
                return "İlgili bilgiyi bulamadım."
            self.save_memory(user_id, result)
            return "✓ Silindi."
        except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
            logger.warning("Claude API hatası (manual_forget) user=%s: %s", user_id, e)
            return "Silme sırasında hata oluştu."
        except OSError as e:
            logger.warning("Dosya hatası (manual_forget) user=%s: %s", user_id, e)
            return "Silme sırasında hata oluştu."
        except Exception:
            logger.exception("Beklenmeyen hata (manual_forget) user=%s", user_id)
            return "Silme sırasında hata oluştu."
