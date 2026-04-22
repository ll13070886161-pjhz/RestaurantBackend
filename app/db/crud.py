from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProductRecord
from app.schemas.product_schema import ProductItem


def _to_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _dedup_key(item: ProductItem) -> Tuple[str, str, str, str, str]:
    name = (item.product_name or "").strip().lower()
    unit_price = "" if item.unit_price is None else str(item.unit_price)
    quantity = "" if item.quantity is None else str(item.quantity)
    unit_amount = "" if item.unit_amount is None else str(item.unit_amount)
    quantity_unit = (item.quantity_unit or "").strip().lower()
    return (name, unit_price, quantity, unit_amount, quantity_unit)


def find_record(session: Session, item: ProductItem) -> Optional[ProductRecord]:
    # Use exact field matching (not a stored hash) to keep transparency and avoid migrations.
    stmt = select(ProductRecord).where(
        ProductRecord.product_name == (item.product_name or ""),
        ProductRecord.unit_price == item.unit_price,
        ProductRecord.quantity == item.quantity,
        ProductRecord.unit_amount == item.unit_amount,
        ProductRecord.quantity_unit == (item.quantity_unit or ""),
    )
    return session.execute(stmt).scalars().first()


def save_item(
    session: Session,
    item: ProductItem,
    *,
    today: Optional[date] = None,
) -> Tuple[str, ProductRecord]:
    """
    Returns (action, record):
    - action: inserted | skipped | accumulated
    Rule:
      - same day: skip if exists
      - different day: accumulate into existing record
    """
    action_today = today or item.order_created_at.date()
    existing = find_record(session, item)
    if existing is None:
        record = ProductRecord(
            product_name=item.product_name,
            unit_price=item.unit_price,
            quantity=item.quantity,
            unit_amount=item.unit_amount,
            quantity_unit=item.quantity_unit,
            total_quantity=item.total_quantity,
            amount=item.amount,
            remarks=item.remarks,
            last_saved_date=action_today,
        )
        session.add(record)
        # SessionLocal uses autoflush=False; flush so repeated checks in same request can see this row.
        session.flush()
        return ("inserted", record)

    if existing.last_saved_date == action_today:
        return ("skipped", existing)

    # Cross-day: accumulate
    existing.last_saved_date = action_today
    existing.quantity = _to_decimal(existing.quantity) if existing.quantity is not None else None
    existing.total_quantity = _to_decimal(existing.total_quantity) if existing.total_quantity is not None else None
    existing.amount = _to_decimal(existing.amount) if existing.amount is not None else None

    inc_qty = _to_decimal(item.quantity)
    inc_total = _to_decimal(item.total_quantity)
    inc_amount = _to_decimal(item.amount)

    if inc_qty is not None:
        existing.quantity = (existing.quantity or Decimal("0")) + inc_qty
    if inc_total is not None:
        existing.total_quantity = (existing.total_quantity or Decimal("0")) + inc_total
    if inc_amount is not None:
        existing.amount = (existing.amount or Decimal("0")) + inc_amount

    # Keep remarks if empty; otherwise append today's note.
    if item.remarks:
        if not existing.remarks:
            existing.remarks = item.remarks
        else:
            existing.remarks = f"{existing.remarks}；{item.remarks}"

    return ("accumulated", existing)

