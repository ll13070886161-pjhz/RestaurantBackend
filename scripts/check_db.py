from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def compose_db_url_from_parts() -> str:
    db_type = (os.getenv("DB_TYPE", "") or "").strip().lower()
    if db_type != "mysql":
        return ""
    host = (os.getenv("DB_HOST", "") or "").strip()
    port = (os.getenv("DB_PORT", "3306") or "3306").strip()
    user = (os.getenv("DB_USER", "") or "").strip()
    password = os.getenv("DB_PASS", "") or ""
    name = (os.getenv("DB_NAME", "") or "").strip()
    params = (os.getenv("DB_PARAMS", "charset=utf8mb4") or "charset=utf8mb4").strip()
    if not all([host, user, name]):
        return ""
    return f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}?{params}"


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    db_url = (os.getenv("DB_URL") or "").strip() or compose_db_url_from_parts() or "sqlite:///./app.db"
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"Database check ok: {db_url.split('@')[-1] if '@' in db_url else db_url}")
        return 0
    except SQLAlchemyError as exc:
        print(f"Database check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
