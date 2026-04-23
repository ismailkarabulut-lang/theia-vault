# Theia Vault

Kişisel kullanım için tasarlanmış, Claude tabanlı Telegram asistan botu. Sohbet etmekle kalmaz — sizi tanır, hatırlar ve zamanla daha iyi hizmet verir.

---

## Özellikler

**Hafıza Sistemi**
Konuşmalar arasında bilgi taşır. Tercihlerinizi, devam eden projelerinizi ve önemli kararlarınızı hatırlar. Siz isteğinizde kayıt yapar, isteğinizde unutur.

**Web Taraması**
Güncel bilgiye ihtiyaç duyduğunuzda internette arama yapar. Bilgi kesim tarihiyle sınırlı kalmaz.

**Hatırlatma Kontrolü**
Belirlediğiniz görev ve hatırlatıcıları takip eder.

**Güvenli Kod Çalıştırma**
Riskli işlemlerde onayınızı alır. Geri alınamaz bir adım atmadan önce size sorar.

**Claude & Claude Code Entegrasyonu**
Claude API üzerinden dil modeli gücü, Claude Code üzerinden ise ajan kabiliyeti. İkisini aynı arayüzden kullanırsınız.

---

## Kurulum

### Gereksinimler

- Python 3.10+
- Telegram Bot Token ([BotFather](https://t.me/botfather))
- Anthropic API anahtarı

### Adımlar

```bash
git clone https://github.com/ismailkarabulut-lang/theia-vault
cd theia-vault
pip install -r requirements.txt
```

`.env` dosyası oluştur:

```env
TELEGRAM_BOT_TOKEN=your_token_here
ANTHROPIC_API_KEY=your_key_here
```

Botu başlat:

```bash
python main.py
```

### Termux (Android) Kurulumu

```bash
pkg update && pkg upgrade
pkg install python git
git clone https://github.com/ismailkarabulut-lang/theia-vault
cd theia-vault
pip install -r requirements.txt
```

Arka planda çalıştırmak için:

```bash
termux-wake-lock
nohup python main.py &
```

> Pil optimizasyonunu kapatmayı unutma: Ayarlar → Uygulama → Termux → Pil → Kısıtlama yok

---

## Hafıza Komutları

| Komut | İşlev |
|-------|-------|
| `/memory` veya `/hafiza` | Hatırladıklarını göster |
| `/kaydet` veya `/remember` | O anki bilgiyi kaydet |
| `/unut` veya `/forget` | Belirtilen bilgiyi sil |
| "bunu hatırla: ..." | Doğal dille kayıt |
| "bunu unut" | Doğal dille silme |

Hafıza dosyaları `memory/users/` altında tutulur ve `.gitignore` ile versiyon kontrolünün dışında bırakılır.

---

## Proje Yapısı

```
theia-vault/
├── main.py              # Bot giriş noktası
├── gatekeeper.py        # Onay mekanizması
├── memory/
│   ├── memory_manager.py
│   ├── __init__.py
│   └── users/           # Kullanıcı hafıza dosyaları (git dışı)
├── .env                 # API anahtarları (git dışı)
└── requirements.txt
```

---

## Notlar

- Hafıza güncellemeleri arka planda çalışır, yanıt süresini etkilemez
- Güncellemeler Claude Haiku ile yapılır, maliyet düşük tutulur
- Her kullanıcının hafızası birbirinden izole tutulur

---

*Kişisel kullanım için geliştirilmiştir.*
