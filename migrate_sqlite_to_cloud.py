import os
import sqlite3
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    text,
)

PROJECT_DIR = Path(__file__).resolve().parent
SQLITE_PATH = PROJECT_DIR / "routine_app.db"


def get_cloud_database_url():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL 환경변수를 먼저 설정하세요.")

    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+pg8000://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+pg8000://", 1)
    return database_url


metadata = MetaData()

routines = Table(
    "routines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)

routine_logs = Table(
    "routine_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("routine_id", Integer, ForeignKey("routines.id"), nullable=False),
    Column("log_date", Date, nullable=False),
    Column("checked", Boolean, nullable=False, default=False),
    UniqueConstraint("routine_id", "log_date", name="uq_routine_logs_routine_date"),
)


def main():
    if not SQLITE_PATH.exists():
        raise SystemExit(f"SQLite 파일을 찾을 수 없습니다: {SQLITE_PATH}")

    engine = create_engine(get_cloud_database_url(), future=True, pool_pre_ping=True)
    metadata.create_all(engine)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_routines = [dict(row) for row in sqlite_conn.execute("SELECT id, name, active FROM routines")]
    sqlite_logs = [dict(row) for row in sqlite_conn.execute("SELECT id, routine_id, log_date, checked FROM routine_logs")]
    sqlite_conn.close()

    with engine.begin() as cloud_conn:
        for row in sqlite_routines:
            cloud_conn.execute(
                text(
                    """
                    INSERT INTO routines (id, name, active)
                    VALUES (:id, :name, :active)
                    ON CONFLICT (id) DO UPDATE
                    SET name = EXCLUDED.name,
                        active = EXCLUDED.active
                    """
                ),
                {
                    "id": row["id"],
                    "name": row["name"],
                    "active": bool(row["active"]),
                },
            )

        for row in sqlite_logs:
            cloud_conn.execute(
                text(
                    """
                    INSERT INTO routine_logs (id, routine_id, log_date, checked)
                    VALUES (:id, :routine_id, :log_date, :checked)
                    ON CONFLICT (routine_id, log_date) DO UPDATE
                    SET checked = EXCLUDED.checked
                    """
                ),
                {
                    "id": row["id"],
                    "routine_id": row["routine_id"],
                    "log_date": row["log_date"],
                    "checked": bool(row["checked"]),
                },
            )

        if engine.dialect.name == "postgresql":
            cloud_conn.execute(
                text("SELECT setval(pg_get_serial_sequence('routines', 'id'), COALESCE((SELECT MAX(id) FROM routines), 1))")
            )
            cloud_conn.execute(
                text("SELECT setval(pg_get_serial_sequence('routine_logs', 'id'), COALESCE((SELECT MAX(id) FROM routine_logs), 1))")
            )

    print(f"완료: 루틴 {len(sqlite_routines)}개, 기록 {len(sqlite_logs)}개를 클라우드 DB에 반영했습니다.")


if __name__ == "__main__":
    main()
