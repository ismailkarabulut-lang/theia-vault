"""Görev/rutin/hatırlatma: sabitler, yardımcı fonksiyonlar, vault export."""

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from core.config import VAULT_DIR
from core.db import db, get_full_history

ASK_TYPE, ASK_CONTENT, ASK_TIME, ASK_RECURRENCE, ASK_RECURRENCE_DETAIL, ASK_CHECK = range(6)

TYPE_LABEL = {"task": "Görev", "routine": "Rutin", "reminder": "Hatırlatma"}

_TR_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart",    4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım",  12: "Aralık",
}


def parse_time(text: str) -> datetime | None:
    text = text.strip()
    now  = datetime.now().replace(second=0, microsecond=0)
    for fmt, today_only in [
        ("%H:%M",           True),
        ("%d.%m %H:%M",     False),
        ("%d.%m.%Y %H:%M",  False),
        ("%Y-%m-%d %H:%M",  False),
    ]:
        try:
            dt = datetime.strptime(text, fmt)
            if today_only:
                dt = now.replace(hour=dt.hour, minute=dt.minute)
                if dt <= now:
                    dt += timedelta(days=1)
            elif dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt
        except ValueError:
            continue
    return None


def next_occurrence(rule: str, after: datetime) -> datetime | None:
    h, m = after.hour, after.minute
    base = after.replace(second=0, microsecond=0)
    if rule == "daily":
        return base + timedelta(days=1)
    if rule.startswith("weekly:"):
        days      = sorted(int(d) for d in rule[7:].split(","))
        candidate = base + timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in days:
                return candidate.replace(hour=h, minute=m, second=0, microsecond=0)
            candidate += timedelta(days=1)
    if rule.startswith("monthly:"):
        day        = int(rule[8:])
        next_month = (base.replace(day=1) + timedelta(days=32)).replace(day=1)
        try:
            return next_month.replace(day=day, hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            return None
    return None


def dt_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_item(r) -> str:
    t     = TYPE_LABEL.get(r["type"], r["type"])
    recur = f" [{r['recurrence']}]" if r["recurrence"] != "none" else ""
    return f"• [{t}]{recur} {r['content']} — {r['scheduled_time']}"


def export_to_vault(user_id: int) -> Path | None:
    rows = get_full_history(user_id)
    if not rows:
        return None

    now      = datetime.now()
    filename = now.strftime("%Y-%m-%d_%H-%M") + ".md"
    date_str = f"{now.day} {_TR_MONTHS[now.month]} {now.year} {now.strftime('%H:%M')}"

    lines = [f"# Theia Konuşması — {date_str}", ""]
    for msg in rows:
        speaker = "İsmail" if msg["role"] == "user" else "Theia"
        lines.append(f"**{speaker}:** {msg['content']}")
        lines.append("")

    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = VAULT_DIR / filename
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


def git_push_vault(filepath: Path) -> tuple[bool, str]:
    is_new = not (VAULT_DIR / ".git").exists()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    if is_new:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return False, "GITHUB_TOKEN .env dosyasında bulunamadı."
        remote_url = f"https://{token}@github.com/ismailkarabulut-lang/theia-vault.git"
        for cmd in [
            ["git", "-C", str(VAULT_DIR), "init"],
            ["git", "-C", str(VAULT_DIR), "remote", "add", "origin", remote_url],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False, f"`{cmd[2]}` hata: {r.stderr.strip()}"

    for cmd in [
        ["git", "-C", str(VAULT_DIR), "add", filepath.name],
        ["git", "-C", str(VAULT_DIR), "commit", "-m",
         f"Konuşma: {filepath.stem.replace('_', ' ')}"],
        ["git", "-C", str(VAULT_DIR), "push", "-u", "origin", "HEAD"],
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, f"`{' '.join(cmd[2:])}` hata: {r.stderr.strip() or r.stdout.strip()}"
    return True, "Push tamamlandı."
