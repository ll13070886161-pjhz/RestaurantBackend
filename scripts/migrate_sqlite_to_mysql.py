from __future__ import annotations

import os
import sys
from typing import Iterable

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    DailySummary,
    ProductRecord,
    PurchaseItem,
    PurchaseReceipt,
    SalesItem,
    SalesReceipt,
)


TABLES_IN_ORDER = [
    ProductRecord,
    PurchaseReceipt,
    SalesReceipt,
    PurchaseItem,
    SalesItem,
    DailySummary,
]


def _rows_to_dicts(rows: Iterable[object]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        data = {col.name: getattr(row, col.name) for col in row.__table__.columns}
        out.append(data)
    return out


def main() -> int:
    source_db_url = os.getenv("SRC_DB_URL", "sqlite:///./app.db")
    target_db_url = os.getenv("DB_URL", "").strip()
    if not target_db_url:
        print("Missing DB_URL for target database.", file=sys.stderr)
        return 2
    if not target_db_url.startswith("mysql"):
        print("DB_URL should point to mysql for this migration script.", file=sys.stderr)
        return 2

    source_engine = create_engine(source_db_url, connect_args={"check_same_thread": False} if source_db_url.startswith("sqlite") else {})
    target_engine = create_engine(target_db_url, pool_pre_ping=True)

    # Ensure target tables exist.
    Base.metadata.create_all(bind=target_engine)

    SourceSession = sessionmaker(bind=source_engine, autocommit=False, autoflush=False)
    TargetSession = sessionmaker(bind=target_engine, autocommit=False, autoflush=False)

    with SourceSession() as source_session, TargetSession() as target_session:
        for model in reversed(TABLES_IN_ORDER):
            target_session.execute(delete(model))
        target_session.commit()

        for model in TABLES_IN_ORDER:
            rows = source_session.execute(select(model)).scalars().all()
            payload = _rows_to_dicts(rows)
            if payload:
                target_session.execute(model.__table__.insert(), payload)
            print(f"Migrated {len(payload)} rows -> {model.__tablename__}")
        target_session.commit()

    print("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
