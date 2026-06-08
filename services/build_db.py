"""
services/build_db.py

CRUD cho 2 bảng:
  - build_apps     : danh sách ứng dụng
  - build_versions : lịch sử build của từng app

Tất cả đều là async (aiosqlite), nhất quán với journal_db.py.
"""

import aiosqlite
import logging
from datetime import datetime
import config

logger = logging.getLogger(__name__)


# ─── Init / Migration ────────────────────────────────────────

async def init_build_db():
    """Khởi tạo bảng build. Gọi cùng với init_db() trong main.py."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS build_apps (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                slug        TEXT    UNIQUE NOT NULL,
                icon        TEXT    DEFAULT '🚀',
                description TEXT    DEFAULT '',
                created_by  INTEGER,
                created_at  TEXT    NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS build_versions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id           INTEGER NOT NULL REFERENCES build_apps(id) ON DELETE CASCADE,
                version          TEXT    NOT NULL,
                git_tag          TEXT    DEFAULT '',
                env              TEXT    DEFAULT 'demo',
                apk_url          TEXT    DEFAULT '',
                testflight_url   TEXT    DEFAULT '',
                testflight_ver   TEXT    DEFAULT '',
                note             TEXT    DEFAULT '',
                is_latest        INTEGER DEFAULT 1,
                created_by       INTEGER,
                created_at       TEXT    NOT NULL
            )
        """)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_build_ver_app ON build_versions (app_id, is_latest)"
        )

        await db.commit()

    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        # Check if git_tag column exists, if not add it
        try:
            await db.execute("ALTER TABLE build_versions ADD COLUMN git_tag TEXT DEFAULT ''")
            await db.commit()
            logger.info("Đã thêm cột git_tag vào bảng build_versions.")
        except Exception:
            pass # Column already exists or table doesn't exist yet

    logger.info("Build DB đã sẵn sàng.")


# ─── Apps ────────────────────────────────────────────────────

async def get_all_apps() -> list[dict]:
    """Trả về danh sách tất cả app, kèm version mới nhất."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.*,
                   v.version   AS latest_version,
                   v.git_tag   AS latest_git_tag,
                   v.env       AS latest_env
            FROM   build_apps a
            LEFT JOIN build_versions v
                   ON v.app_id = a.id AND v.is_latest = 1
            ORDER  BY a.id
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_app(app_id: int) -> dict | None:
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM build_apps WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def add_app(name: str, slug: str, icon: str = "🚀",
                  description: str = "", created_by: int = None) -> int:
    """Thêm app mới. Trả về id."""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO build_apps (name, slug, icon, description, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, slug, icon, description, created_by, now),
        )
        app_id = cur.lastrowid
        await db.commit()
    logger.info(f"Đã thêm app #{app_id}: {name}")
    return app_id


async def update_app(app_id: int, **fields) -> bool:
    """Cập nhật các field của app (name, slug, icon, description)."""
    allowed = {"name", "slug", "icon", "description"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [app_id]
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute(
            f"UPDATE build_apps SET {set_clause} WHERE id = ?", values
        )
        await db.commit()
    return True


async def delete_app(app_id: int) -> bool:
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("DELETE FROM build_apps WHERE id = ?", (app_id,))
        await db.commit()
    return True


# ─── Versions ────────────────────────────────────────────────

async def get_latest_version(app_id: int) -> dict | None:
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM build_versions WHERE app_id = ? AND is_latest = 1 LIMIT 1",
            (app_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_version_history(app_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM build_versions WHERE app_id = ?
               ORDER BY id DESC LIMIT ?""",
            (app_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def add_version(
    app_id: int,
    version: str,
    git_tag: str = "",
    env: str = "demo",
    apk_url: str = "",
    testflight_url: str = "",
    testflight_ver: str = "",
    note: str = "",
    created_by: int = None,
) -> int:
    """Thêm version mới, tự động đặt is_latest=1 và reset các version cũ."""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        # Reset is_latest của tất cả version cũ
        await db.execute(
            "UPDATE build_versions SET is_latest = 0 WHERE app_id = ?", (app_id,)
        )
        cur = await db.execute(
            """INSERT INTO build_versions
               (app_id, version, git_tag, env, apk_url, testflight_url, testflight_ver,
                note, is_latest, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (app_id, version, git_tag, env, apk_url, testflight_url, testflight_ver,
             note, created_by, now),
        )
        ver_id = cur.lastrowid
        await db.commit()
    logger.info(f"Thêm version #{ver_id} ({version}) cho app #{app_id}")
    return ver_id


async def update_version(version_id: int, **fields) -> bool:
    """Cập nhật các field của version."""
    allowed = {"version", "git_tag", "env", "apk_url", "testflight_url", "testflight_ver", "note"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [version_id]
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute(
            f"UPDATE build_versions SET {set_clause} WHERE id = ?", values
        )
        await db.commit()
    return True


async def delete_version(version_id: int) -> bool:
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("DELETE FROM build_versions WHERE id = ?", (version_id,))
        await db.commit()
    return True


# ─── Seed dữ liệu mẫu ────────────────────────────────────────

async def seed_sample_data():
    """
    Chèn dữ liệu mẫu nếu chưa có app nào.
    Gọi một lần khi khởi động (sau init_build_db).
    """
    apps = await get_all_apps()
    if apps:
        return  # Đã có data, bỏ qua

    logger.info("Seeding build sample data...")

    app_id = await add_app(
        name="SmartTown Demo",
        slug="smarttown_demo",
        icon="🚀",
        description="Điều hành khu phố, ấp",
    )
    await add_version(
        app_id=app_id,
        version="v1.1.2",
        env="demo",
        apk_url="https://drive.google.com/file/d/1eS18sz3m7R3FGVOULLVP2ufFRqYFGm0C/view",
        testflight_url="https://testflight.apple.com/join/example",
        testflight_ver="1.2.5 (1)",
        note="Release ổn định — khu phố ấp v1",
    )
    logger.info("Seed xong.")
