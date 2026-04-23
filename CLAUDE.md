# CLAUDE.md

Bu dosya Claude Code'un bu repoda çalışırken uyması gereken kurallardır.

## Proje

**Theia** — Kaptan İsmail Karabulut'un kişisel AI asistan sistemi.
Telegram üzerinden çalışır. Dil: Türkçe.

## Mevcut Stack

- Python 3.13
- python-telegram-bot 22.7
- Anthropic Claude API (claude-sonnet-4-5 veya üstü)
- SQLite (theia.db)
- Flask (ileride API katmanı için)
- APScheduler (zamanlanmış görevler)

## Dosya Yapısı

- `theia_telegram.py` — Telegram bot, ana giriş noktası
- `theia_core.py` — LLM katmanı (GÜNCELLENECEk: Ollama → Claude API)
- `gatekeeper.py` — Komut onay ve risk sınıflandırma sistemi
- `theia_terminal.py` — Terminal CLI
- `theia.db` — SQLite veritabanı (tasks tablosu)
- `.env` — TELEGRAM_TOKEN, CHAT_ID, ANTHROPIC_API_KEY

## Çalıştırma

```bash
cd ~/theia
python3 theia_telegram.py   # Telegram bot
python3 gatekeeper.py       # Komut onay sistemi
python3 gatekeeper.py --dry-run  # Test modu
```

## Geliştirme Kuralları

- Her değişiklikten önce ne yapacağını söyle, onay bekle
- Dosyaları silme, taşıma — sadece düzenle veya oluştur
- git push, deploy, dış API çağrısı öncesi MUTLAKA dur ve sor
- Mevcut Türkçe kullanıcı mesajlarını koru
- Yeni kullanıcı mesajları Türkçe olacak
- theia.db'ye yazma işlemi öncesi sor
- Gereksiz bağımlılık ekleme
- Tek dosyayı düzenle, tüm projeyi yeniden yazma

## Mimari Hedef (Geçiş Süreci)

theia_core.py şu an Ollama'ya bağlı (localhost:11434, llama3.2).
Hedef: Anthropic Claude API'ye geçiş.
Geçiş tamamlanana kadar mevcut kodu koru, paralel çalıştırma yapma.

## Test

```bash
python3 -c "from theia_core import ask_theia; print(ask_theia('Merhaba'))"
python3 gatekeeper.py --dry-run
```
