"""Web Agent — gerçek zamanlı veri + arama + RSS haber."""

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

_WEB_TRIGGERS = {
    "haber", "bugün", "şimdi", "kur", "dolar", "euro", "sterlin",
    "hava", "sıcaklık", "derece", "güncel", "son dakika", "kaç lira",
    "fiyat", "borsa", "ara", "bul", "araştır", "yapay zeka", "teknoloji",
    "ai", "tech",
}

# RSS kaynakları — kategori bazlı
RSS_FEEDS = {
    "teknoloji": [
        "https://feeds.feedburner.com/TechCrunch",
        "https://www.theverge.com/rss/index.xml",
    ],
    "yapay_zeka": [
        "https://feeds.feedburner.com/TechCrunch/artificial-intelligence",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    ],
    "genel": [
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
    ],
}

# Hava kodu → açıklama (Open-Meteo WMO kodları)
_WMO = {
    0: "Açık", 1: "Çoğunlukla açık", 2: "Parçalı bulutlu", 3: "Bulutlu",
    45: "Sisli", 48: "Sisli",
    51: "Hafif çisenti", 53: "Orta çisenti", 55: "Yoğun çisenti",
    61: "Hafif yağmur", 63: "Orta yağmur", 65: "Şiddetli yağmur",
    71: "Hafif kar", 73: "Orta kar", 75: "Yoğun kar",
    80: "Hafif sağanak", 81: "Orta sağanak", 82: "Şiddetli sağanak",
    95: "Fırtına", 99: "Dolu ile fırtına",
}


class WebAgent:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def needs_web(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in _WEB_TRIGGERS)

    async def run(self, query: str) -> dict:
        if not self.needs_web(query):
            return {"source": "none", "data": None}

        results = await asyncio.gather(
            self._fetch_realtime(query),
            self._fetch_news(query),
            return_exceptions=True,
        )

        realtime = results[0] if not isinstance(results[0], Exception) else None
        news     = results[1] if not isinstance(results[1], Exception) else None

        if realtime is None and news is None:
            return {"source": "none", "data": None}

        return {"source": "web", "realtime": realtime, "news": news}

    # ── Gerçek zamanlı veri ───────────────────────────────────────────────

    async def _fetch_realtime(self, query: str) -> dict | None:
        q = query.lower()
        if any(w in q for w in ["dolar", "euro", "sterlin", "kur", "kaç lira", "borsa"]):
            return await self._fetch_exchange()
        if any(w in q for w in ["hava", "sıcaklık", "derece", "haftalık", "tahmin"]):
            return await self._fetch_weather_weekly()
        return None

    async def _fetch_exchange(self) -> dict | None:
        try:
            r = await self.client.get("https://api.exchangerate-api.com/v4/latest/USD")
            d = r.json()
            rates = d.get("rates", {})
            try_ = rates.get("TRY", 0)
            eur  = rates.get("EUR", 1)
            return {
                "type": "kur",
                "USD/TRY": round(try_, 2),
                "EUR/TRY": round(try_ / eur, 2) if eur else None,
            }
        except Exception as e:
            log.warning("Kur hatası: %s", e)
            return None

    async def _fetch_weather_weekly(self) -> dict | None:
        """Open-Meteo 7 günlük tahmin — İstanbul."""
        try:
            r = await self.client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 41.01,
                    "longitude": 28.97,
                    "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max",
                    "current_weather": True,
                    "timezone": "Europe/Istanbul",
                    "forecast_days": 7,
                },
            )
            data  = r.json()
            daily = data.get("daily", {})
            cw    = data.get("current_weather", {})

            dates     = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            codes     = daily.get("weathercode", [])
            precip    = daily.get("precipitation_probability_max", [])

            days = []
            for i, date in enumerate(dates):
                dt    = datetime.strptime(date, "%Y-%m-%d")
                label = dt.strftime("%a %d/%m")
                code  = codes[i] if i < len(codes) else 0
                days.append({
                    "gün":     label,
                    "durum":   _WMO.get(code, "Bilinmiyor"),
                    "max":     max_temps[i] if i < len(max_temps) else None,
                    "min":     min_temps[i] if i < len(min_temps) else None,
                    "yagis_%": precip[i] if i < len(precip) else None,
                })

            return {
                "type": "hava",
                "şehir": "İstanbul",
                "şu_an": {
                    "sıcaklık": cw.get("temperature"),
                    "durum": _WMO.get(cw.get("weathercode", 0), ""),
                },
                "7_gun": days,
            }
        except Exception as e:
            log.warning("Hava hatası: %s", e)
            return None

    # ── RSS Haber ─────────────────────────────────────────────────────────

    async def _fetch_news(self, query: str) -> list[dict] | None:
        q = query.lower()

        if any(w in q for w in ["yapay zeka", "ai", "yapay"]):
            feeds = RSS_FEEDS["yapay_zeka"]
        elif any(w in q for w in ["teknoloji", "tech", "haber"]):
            feeds = RSS_FEEDS["teknoloji"] + RSS_FEEDS["genel"]
        else:
            return None

        results = await asyncio.gather(
            *[self._parse_rss(url) for url in feeds],
            return_exceptions=True,
        )

        items = []
        for r in results:
            if isinstance(r, list):
                items.extend(r)

        seen, unique = set(), []
        for item in items:
            if item["title"] not in seen:
                seen.add(item["title"])
                unique.append(item)
            if len(unique) >= 5:
                break

        return unique if unique else None

    async def _parse_rss(self, url: str) -> list[dict]:
        try:
            r    = await self.client.get(url, follow_redirects=True)
            root = ET.fromstring(r.text)
            ns   = {"atom": "http://www.w3.org/2005/Atom"}
            items = []

            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                if title:
                    items.append({"title": title, "link": link})

            if not items:
                for entry in root.findall(".//atom:entry", ns)[:5]:
                    title   = entry.findtext("atom:title", "", ns).strip()
                    link_el = entry.find("atom:link", ns)
                    link    = link_el.get("href", "") if link_el is not None else ""
                    if title:
                        items.append({"title": title, "link": link})

            return items
        except Exception as e:
            log.warning("RSS parse hatası (%s): %s", url, e)
            return []

    # ── Prompt formatı ────────────────────────────────────────────────────

    def format_for_prompt(self, result: dict) -> str:
        if result.get("source") != "web":
            return ""

        parts = []

        rt = result.get("realtime")
        if rt:
            if rt.get("type") == "kur":
                parts.append(
                    f"Güncel kur: 1 USD = {rt['USD/TRY']} TL, "
                    f"1 EUR = {rt.get('EUR/TRY', '?')} TL"
                )
            elif rt.get("type") == "hava":
                now = rt.get("şu_an", {})
                parts.append(
                    f"İstanbul şu an: {now.get('sıcaklık')}C, {now.get('durum')}"
                )
                lines = ["7 gunluk tahmin:"]
                for d in rt.get("7_gun", []):
                    yagis = f", yagis %{d['yagis_%']}" if d.get("yagis_%") else ""
                    lines.append(
                        f"  {d['gun']}: {d['durum']}, "
                        f"{d['min']}-{d['max']}C{yagis}"
                    )
                parts.append("\n".join(lines))

        news = result.get("news")
        if news:
            lines = ["Son haberler:"]
            for item in news:
                lines.append(f"  - {item['title']}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
