from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PurchaseItem, PurchaseReceipt, SalesItem, SalesReceipt
from app.schemas.product_schema import ProductItem
from app.schemas.sales_schema import SalesLineItem


def _to_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _purchase_dedup_key(item: ProductItem) -> str:
    name = (item.product_name or "").strip().lower()
    unit_price = "" if item.unit_price is None else str(item.unit_price)
    quantity = "" if item.quantity is None else str(item.quantity)
    unit_amount = "" if item.unit_amount is None else str(item.unit_amount)
    quantity_unit = (item.quantity_unit or "").strip().lower()
    raw = "|".join([name, unit_price, quantity, unit_amount, quantity_unit])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sales_dedup_key(item: SalesLineItem) -> str:
    name = (item.item_name or "").strip().lower()
    unit_price = "" if item.unit_price is None else str(item.unit_price)
    quantity = "" if item.quantity is None else str(item.quantity)
    raw = "|".join([name, unit_price, quantity])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_purchase_receipt(
    session: Session,
    *,
    biz_date: date,
    source_image_path: str,
    raw_llm_response: str = "",
) -> PurchaseReceipt:
    rec = PurchaseReceipt(
        biz_date=biz_date,
        source_image_path=source_image_path,
        raw_llm_response=raw_llm_response,
    )
    session.add(rec)
    session.flush()
    return rec


def upsert_purchase_item(
    session: Session,
    *,
    receipt_id: int,
    biz_date: date,
    item: ProductItem,
    consumption_type: Optional[str] = None,
) -> Tuple[str, PurchaseItem]:
    key = _purchase_dedup_key(item)
    existing = session.execute(select(PurchaseItem).where(PurchaseItem.dedup_key == key)).scalars().first()
    if existing is None:
        row = PurchaseItem(
            receipt_id=receipt_id,
            item_name=item.product_name,
            quantity=item.quantity,
            unit_amount=item.unit_amount,
            quantity_unit=item.quantity_unit,
            total_quantity=item.total_quantity,
            unit_price=item.unit_price,
            amount=item.amount,
            remarks=item.remarks,
            consumption_type=consumption_type,
            dedup_key=key,
            last_saved_date=biz_date,
        )
        session.add(row)
        # SessionLocal uses autoflush=False; flush so later selects in same request can see this row.
        session.flush()
        return "inserted", row

    if existing.last_saved_date == biz_date:
        return "skipped", existing

    # Cross-day accumulate
    existing.receipt_id = receipt_id
    existing.last_saved_date = biz_date
    if consumption_type:
        existing.consumption_type = consumption_type

    inc_amount = _to_decimal(item.amount)
    inc_total = _to_decimal(item.total_quantity)
    inc_qty = _to_decimal(item.quantity)

    existing.amount = _to_decimal(existing.amount)
    existing.total_quantity = _to_decimal(existing.total_quantity)
    existing.quantity = _to_decimal(existing.quantity)

    if inc_amount is not None:
        existing.amount = (existing.amount or Decimal("0")) + inc_amount
    if inc_total is not None:
        existing.total_quantity = (existing.total_quantity or Decimal("0")) + inc_total
    if inc_qty is not None:
        existing.quantity = (existing.quantity or Decimal("0")) + inc_qty

    if item.remarks:
        existing.remarks = f"{existing.remarks}；{item.remarks}" if existing.remarks else item.remarks

    return "accumulated", existing


def create_sales_receipt(
    session: Session,
    *,
    biz_date: date,
    source_image_path: str,
    raw_llm_response: str = "",
) -> SalesReceipt:
    rec = SalesReceipt(
        biz_date=biz_date,
        source_image_path=source_image_path,
        raw_llm_response=raw_llm_response,
    )
    session.add(rec)
    session.flush()
    return rec


def upsert_sales_item(
    session: Session,
    *,
    receipt_id: int,
    biz_date: date,
    item: SalesLineItem,
) -> Tuple[str, SalesItem]:
    key = _sales_dedup_key(item)
    existing = session.execute(select(SalesItem).where(SalesItem.dedup_key == key)).scalars().first()
    if existing is None:
        row = SalesItem(
            receipt_id=receipt_id,
            item_name=item.item_name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            amount=item.amount,
            remarks=item.remarks,
            dedup_key=key,
            last_saved_date=biz_date,
        )
        session.add(row)
        # SessionLocal uses autoflush=False; flush so later selects in same request can see this row.
        session.flush()
        return "inserted", row

    if existing.last_saved_date == biz_date:
        return "skipped", existing

    existing.receipt_id = receipt_id
    existing.last_saved_date = biz_date

    inc_amount = _to_decimal(item.amount)
    inc_qty = _to_decimal(item.quantity)

    existing.amount = _to_decimal(existing.amount)
    existing.quantity = _to_decimal(existing.quantity)

    if inc_amount is not None:
        existing.amount = (existing.amount or Decimal("0")) + inc_amount
    if inc_qty is not None:
        existing.quantity = (existing.quantity or Decimal("0")) + inc_qty

    if item.remarks:
        existing.remarks = f"{existing.remarks}；{item.remarks}" if existing.remarks else item.remarks

    return "accumulated", existing

