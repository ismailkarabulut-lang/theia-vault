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

- `main.py` — Telegram bot, ana giriş noktası (handler kayıt + uygulama başlatma)
- `core/config.py` — Ayarlar, Anthropic istemcisi, yetki kontrolü (`ok()`)
- `core/db.py` — SQLite veritabanı işlemleri
- `handlers/start.py` — /start komutu
- `handlers/message.py` — Genel mesaj işleyici, Claude API entegrasyonu
- `handlers/shell.py` — /cmd komutu, komut onay akışı ve callback'ler
- `handlers/schedule.py` — /ekle, /liste, /sifirla, cron job, hatırlatma callback'leri
- `handlers/memory.py` — /memory, /kaydet, /unut komutları
- `handlers/media.py` — Medya komutları (yer tutucu)
- `gatekeeper.py` — Risk sınıflandırma, SandboxExecutor, denetim logu
- `memory/memory_manager.py` — Kullanıcı başına kalıcı hafıza sistemi
- `test_gatekeeper.py` — RiskClassifier birim testleri
- `test_sandbox.py` — SandboxExecutor birim testleri
- `requirements.txt` — Bağımlılıklar
- `theia.db` — SQLite veritabanı (items, checks, conversations tabloları)
- `.env` — TELEGRAM_TOKEN, CHAT_ID, USER_ID, ANTHROPIC_API_KEY

## Çalıştırma

```bash
cd ~/theia
python3 main.py             # Telegram bot
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

## Mimari

Claude API geçişi tamamlandı. `handlers/message.py` claude-sonnet-4-5 kullanıyor.
`memory/memory_manager.py` claude-haiku-4-5 kullanıyor (hafıza özeti için).
Ollama bağımlılığı tamamen kaldırıldı.

## Test

```bash
python3 -m pytest test_gatekeeper.py test_sandbox.py -v
python3 gatekeeper.py --dry-run
```
