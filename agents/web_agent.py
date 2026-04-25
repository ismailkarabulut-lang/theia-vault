"""Web Agent — 🌍 / & prefix tetikli Anthropic web_search_20250305 tool use."""

import asyncio
import logging

import anthropic

from core.config import WEB_TOOLS, claude

log = logging.getLogger("web_agent")

# handlers/message.py bu sabiti import eder
WEB_PREFIXES: frozenset[str] = frozenset({"🌍", "&"})

_MODEL      = "claude-sonnet-4-6"
_MAX_TOKENS = 1024
_SYSTEM     = (
    "Web'de ara, kullanıcının sorusunu Türkçe kısa özetle. "
    "Gereksiz link listesi veya kaynak ekleme. "
    "Bilgi bulunamazsa sadece 'Sonuç bulunamadı.' yaz."
)


def has_prefix(text: str) -> tuple[bool, str]:
    """
    Mesajın başındaki 🌍 / & prefix'ini kontrol eder.
    Dönüş: (prefix_var_mı, temizlenmiş_metin)
    """
    stripped = text.strip()
    for prefix in WEB_PREFIXES:
        if stripped.startswith(prefix):
            return True, stripped[len(prefix):].strip()
    return False, stripped


# ── Sync katmanı ──────────────────────────────────────────────────────────────

def _sync_search(query: str) -> str:
    """
    Anthropic web_search_20250305 ile tek API çağrısı.
    Tool use loop: Anthropic built-in tool sonuçları doğrudan content'e yazar,
    ancak nadiren tool_use stop_reason dönerse max 3 tur döner.
    """
    messages: list[dict] = [{"role": "user", "content": query}]

    for _ in range(3):
        resp = claude.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            tools=WEB_TOOLS,
            messages=messages,
        )

        # Her turda text blokları topla
        text_parts = [b.text for b in resp.content if hasattr(b, "text")]

        if resp.stop_reason == "end_turn":
            text = "\n".join(text_parts).strip()
            return f"[Web Araması]\n{text}" if text else ""

        if resp.stop_reason == "tool_use":
            # Built-in tool: tool_result placeholder ekle, devam et
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tu.id, "content": ""}
                    for tu in tool_uses
                ],
            })
            continue

        # Beklenmeyen stop_reason — varsa metni döndür
        text = "\n".join(text_parts).strip()
        return f"[Web Araması]\n{text}" if text else ""

    return ""


# ── Public async API ──────────────────────────────────────────────────────────

async def search(query: str) -> str:
    """
    Web araması yapar ve '[Web Araması]\\n...' formatında sonuç döner.
    Sonuç yoksa veya hata olursa boş string döner.
    """
    try:
        return await asyncio.to_thread(_sync_search, query)
    except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
        log.warning("web search API hatası: %s", e)
        return ""
    except Exception:
        log.exception("web search başarısız query=%r", query)
        return ""
