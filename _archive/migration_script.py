"""memory/users/*.md → entries tablosu migrasyonu.

Çalıştır:  python3 memory/migration_script.py
İdempotent: aynı user_id için ikinci çalıştırmada atlar.
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Proje kökünü path'e ekle (script doğrudan çalıştırılınca)
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import db, init_db

USERS_DIR = Path(__file__).parent / "users"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def migrate() -> None:
    init_db()
    now = _now()

    md_files = sorted(USERS_DIR.glob("*.md"))
    if not md_files:
        print("Migrasyon yapılacak .md dosyası bulunamadı.")
        return

    migrated = skipped = 0

    for path in md_files:
        user_id = path.stem
        content = path.read_text(encoding="utf-8").strip()

        if not content:
            print(f"  ATLA (boş)  {path.name}")
            skipped += 1
            continue

        with db() as c:
            # İdempotency: aynı user_id'den migrasyon kaydı var mı?
            existing = c.execute(
                "SELECT id FROM entries "
                "WHERE created_by='migration' AND json_extract(meta,'$.user_id')=?",
                (user_id,),
            ).fetchone()

            if existing:
                print(f"  ATLA (var)  {path.name}")
                skipped += 1
                continue

            entry_id = str(uuid.uuid4())
            meta     = json.dumps({"user_id": user_id, "migrated_from": path.name})

            c.execute(
                """
                INSERT INTO entries
                    (id, content, summary, topic_slug, source, created_by,
                     confidence, version, deleted, created_at, updated_at, meta)
                VALUES (?, ?, NULL, NULL, 'manual', 'migration',
                        1.0, 1, 0, ?, ?, ?)
                """,
                (entry_id, content, now, now, meta),
            )
            c.execute(
                """
                INSERT INTO audit (action, target_id, actor, status, detail, ts)
                VALUES ('migrate', ?, 'migration', 'ok', ?, ?)
                """,
                (entry_id, f"user_id={user_id} file={path.name}", now),
            )
            c.execute(
                """
                INSERT INTO queue (job_type, payload, status, attempts, created_at, updated_at)
                VALUES ('summarize', ?, 'pending', 0, ?, ?)
                """,
                (json.dumps({"entry_id": entry_id}), now, now),
            )

        print(f"  OK          {path.name}  →  {entry_id[:8]}…")
        migrated += 1

    print(f"\nToplam: {migrated} migre edildi, {skipped} atlandı.")


if __name__ == "__main__":
    migrate()
