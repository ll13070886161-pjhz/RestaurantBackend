from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


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

    required = ["LLM_PROVIDER_NAME", "LLM_API_KEY", "LLM_MODEL_NAME", "LLM_BASE_URL"]
    missing = [k for k in required if not (os.getenv(k) or "").strip()]
    if missing:
        print("Config check failed. Missing env:", ", ".join(missing), file=sys.stderr)
        print("Hint: copy and edit .env:", file=sys.stderr)
        print("  cp .env.example .env", file=sys.stderr)
        return 2

    base_url = (os.getenv("LLM_BASE_URL") or "").strip()
    if base_url.endswith("/chat/completions"):
        print(
            "Warning: LLM_BASE_URL ends with /chat/completions. "
            "It's OK, but recommend using https://.../api/v3 (we normalize in code).",
            file=sys.stderr,
        )

    db_url = (os.getenv("DB_URL") or "").strip() or compose_db_url_from_parts()
    if not db_url:
        print("Warning: DB_URL is empty, fallback sqlite:///./app.db will be used.", file=sys.stderr)
    elif db_url.startswith("mysql"):
        try:
            import pymysql  # noqa: F401
        except Exception:
            print("Config check failed: MySQL DB_URL detected but PyMySQL is not installed.", file=sys.stderr)
            print("Run: make init", file=sys.stderr)
            return 2

    print("Config check ok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
