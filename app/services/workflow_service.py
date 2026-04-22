from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from difflib import get_close_matches
from typing import Any, Callable, List, Optional

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.domain_crud import (
    create_purchase_receipt,
    create_sales_receipt,
    _to_decimal,
    upsert_purchase_item,
    upsert_sales_item,
)
from app.db.models import BomIngredient, PurchaseItem, SalesConsumptionLog
from app.schemas.product_schema import ProductItem
from app.schemas.sales_schema import SalesLineItem
from app.services.excel_writer import write_items_to_excel, write_sales_to_excel
from app.services.material_classification import (
    exists_in_bom,
    match_non_instant_rule,
    normalize_material_name,
)


logger = logging.getLogger(__name__)


def parse_biz_date(value: str) -> date:
    if not value:
        return datetime.now().date()
    return date.fromisoformat(value)


def save_uploaded_file(content: bytes, filename: str, *, category: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_name = (filename or "upload").replace("/", "_").replace("\\", "_")
    out_dir = settings.upload_dir / category
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ts}_{safe_name}"
    path.write_bytes(content)
    return str(path)


def is_empty_product_item(item: ProductItem) -> bool:
    return (
        not (item.product_name or "").strip()
        and item.unit_price is None
        and item.quantity is None
        and item.unit_amount is None
        and not (item.quantity_unit or "").strip()
        and item.total_quantity is None
        and item.amount is None
        and not (item.remarks or "").strip()
    )


async def parse_purchase_images_flow(
    files: List[UploadFile],
    *,
    biz_date: str,
    llm_adapter: Any,
) -> dict:
    parsed_items: List[ProductItem] = []
    errors: list[dict] = []
    image_paths: list[str] = []
    dt_now = datetime.now()
    use_date = parse_biz_date(biz_date)

    for file in files:
        content = await file.read()
        if not content:
            errors.append({"file": file.filename, "error": "Empty file"})
            continue
        image_paths.append(save_uploaded_file(content, file.filename, category=f"purchase/{use_date.isoformat()}"))
        result = llm_adapter.parse_product_from_image(image_bytes=content, upload_time=dt_now)
        if result.success:
            rows = result.items if result.items else ([result.item] if result.item else [])
            parsed_items.extend([r for r in rows if r and not is_empty_product_item(r)])
        else:
            errors.append({"file": file.filename, "error": result.error})

    purchase_output_dir = settings.output_dir / "purchase" / use_date.isoformat()
    purchase_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = write_items_to_excel(parsed_items, purchase_output_dir)
    logger.info(
        "purchase.parse done: biz_date=%s images=%s items=%s errors=%s",
        use_date.isoformat(),
        len(image_paths),
        len(parsed_items),
        len(errors),
    )
    return {
        "biz_date": use_date.isoformat(),
        "source_image_paths": image_paths,
        "errors": errors,
        "report_path": report_path,
        "preview": [item.model_dump(mode="json") for item in parsed_items],
    }


async def parse_sales_images_flow(
    files: List[UploadFile],
    *,
    biz_date: str,
    llm_adapter: Any,
) -> dict:
    parsed_items: List[SalesLineItem] = []
    errors: list[dict] = []
    image_paths: list[str] = []
    dt_now = datetime.now()
    use_date = parse_biz_date(biz_date)

    for file in files:
        content = await file.read()
        if not content:
            errors.append({"file": file.filename, "error": "Empty file"})
            continue
        image_paths.append(save_uploaded_file(content, file.filename, category=f"sales/{use_date.isoformat()}"))
        ok, rows, err = llm_adapter.parse_sales_from_image(image_bytes=content, upload_time=dt_now)
        if ok:
            parsed_items.extend([r for r in rows if r and (r.item_name or "").strip()])
        else:
            errors.append({"file": file.filename, "error": err})

    sales_output_dir = settings.output_dir / "sales" / use_date.isoformat()
    sales_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = write_sales_to_excel(parsed_items, sales_output_dir)
    logger.info(
        "sales.parse done: biz_date=%s images=%s items=%s errors=%s",
        use_date.isoformat(),
        len(image_paths),
        len(parsed_items),
        len(errors),
    )
    return {
        "biz_date": use_date.isoformat(),
        "source_image_paths": image_paths,
        "errors": errors,
        "report_path": report_path,
        "preview": [item.model_dump(mode="json") for item in parsed_items],
        "items": parsed_items,
    }


def _collect_bom_map(session: Session, dish_names: list[str]) -> dict[str, list[BomIngredient]]:
    clean_names = sorted({normalize_material_name(n) for n in dish_names if (n or "").strip()})
    if not clean_names:
        return {}
    stmt = select(BomIngredient).where(func.lower(BomIngredient.dish_name).in_(clean_names))
    rows = session.execute(stmt).scalars().all()
    bom_map: dict[str, list[BomIngredient]] = {}
    for row in rows:
        bom_map.setdefault(normalize_material_name(row.dish_name), []).append(row)
    return bom_map


def _collect_inventory_map(session: Session, ingredient_names: list[str]) -> dict[str, list[PurchaseItem]]:
    clean_names = sorted({normalize_material_name(n) for n in ingredient_names if (n or "").strip()})
    if not clean_names:
        return {}
    stmt = (
        select(PurchaseItem)
        .where(
            func.lower(PurchaseItem.item_name).in_(clean_names),
            PurchaseItem.consumption_type == "instant",
        )
        .order_by(PurchaseItem.updated_at.asc())
    )
    rows = session.execute(stmt).scalars().all()
    inventory_map: dict[str, list[PurchaseItem]] = {}
    for row in rows:
        inventory_map.setdefault(normalize_material_name(row.item_name), []).append(row)
    return inventory_map


def deduct_inventory_by_sales(
    *,
    session: Session,
    sales_items: list[SalesLineItem],
) -> dict:
    bom_map = _collect_bom_map(session, [item.item_name for item in sales_items])
    inventory_map = _collect_inventory_map(
        session,
        [ing.ingredient_name for rows in bom_map.values() for ing in rows],
    )

    consumption_details: list[dict] = []
    exception_details: list[dict] = []
    for item in sales_items:
        sold_qty = _to_decimal(item.quantity) or Decimal("0")
        dish_key = normalize_material_name(item.item_name)
        bom_rows = bom_map.get(dish_key, [])
        if not bom_rows:
            exception_details.append(
                {
                    "dish_name": item.item_name,
                    "type": "dish_not_found_in_bom",
                    "message": "未匹配到配方，未执行扣减",
                }
            )
            continue
        for bom in bom_rows:
            unit_usage = _to_decimal(bom.ingredient_amount) or Decimal("0")
            required = unit_usage * sold_qty
            remain_need = required
            stocks = inventory_map.get(normalize_material_name(bom.ingredient_name), [])

            for stock in stocks:
                if remain_need <= 0:
                    break
                current = _to_decimal(stock.total_quantity)
                if current is None:
                    current = _to_decimal(stock.quantity) or Decimal("0")
                deducted = min(current, remain_need)
                current_after = current - deducted
                stock.total_quantity = current_after
                remain_need -= deducted

            consumption_details.append(
                {
                    "dish_name": item.item_name,
                    "sold_quantity": str(sold_qty),
                    "ingredient_name": bom.ingredient_name,
                    "ingredient_unit": bom.ingredient_unit,
                    "required_quantity": str(required),
                    "deducted_quantity": str(required - remain_need),
                    "shortage_quantity": str(remain_need if remain_need > 0 else Decimal("0")),
                }
            )
            if remain_need > 0:
                exception_details.append(
                    {
                        "dish_name": item.item_name,
                        "ingredient_name": bom.ingredient_name,
                        "type": "inventory_shortage",
                        "message": "库存不足，已部分扣减",
                        "shortage_quantity": str(remain_need),
                    }
                )

    remaining_rows = session.execute(
        select(PurchaseItem).where(PurchaseItem.consumption_type == "instant").order_by(PurchaseItem.updated_at.desc()).limit(500)
    ).scalars().all()
    remaining_inventory = [
        {
            "item_name": r.item_name,
            "total_quantity": str(_to_decimal(r.total_quantity) or Decimal("0")),
            "quantity_unit": r.quantity_unit,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in remaining_rows
    ]
    return {
        "consumption": consumption_details,
        "remaining_inventory": remaining_inventory,
        "exception_details": exception_details,
    }


def suggest_dish_names(
    *,
    session: Session,
    query: str,
    limit: int = 8,
) -> list[str]:
    keyword = (query or "").strip()
    if not keyword:
        return []
    rows = session.execute(select(BomIngredient.dish_name).distinct()).scalars().all()
    dishes = [r for r in rows if (r or "").strip()]
    contains = [name for name in dishes if keyword.lower() in name.lower()]
    if len(contains) >= limit:
        return contains[:limit]
    fuzzy = get_close_matches(keyword, dishes, n=limit, cutoff=0.35)
    merged: list[str] = []
    for name in contains + fuzzy:
        if name not in merged:
            merged.append(name)
        if len(merged) >= limit:
            break
    return merged


def process_sales_and_deduct_flow(
    *,
    biz_date: str,
    source_image_paths: List[str],
    items: List[SalesLineItem],
    session_factory: Callable[[], Session],
) -> dict:
    use_date = parse_biz_date(biz_date)
    db = session_factory()
    inserted = skipped = accumulated = 0
    try:
        source_path = source_image_paths[0] if source_image_paths else ""
        receipt = create_sales_receipt(db, biz_date=use_date, source_image_path=source_path)
        saved_rows: list[dict] = []
        for item in items:
            action, row = upsert_sales_item(db, receipt_id=receipt.id, biz_date=use_date, item=item)
            if action == "inserted":
                inserted += 1
            elif action == "skipped":
                skipped += 1
            else:
                accumulated += 1
            saved_rows.append({"action": action, "item_name": row.item_name, "id": row.id})

        deduction_result = deduct_inventory_by_sales(session=db, sales_items=items)
        db.add_all(
            [
                SalesConsumptionLog(
                    receipt_id=receipt.id,
                    biz_date=use_date,
                    dish_name=row.get("dish_name", ""),
                    ingredient_name=row.get("ingredient_name", ""),
                    ingredient_unit=row.get("ingredient_unit", ""),
                    required_quantity=_to_decimal(row.get("required_quantity")),
                    deducted_quantity=_to_decimal(row.get("deducted_quantity")),
                    shortage_quantity=_to_decimal(row.get("shortage_quantity")),
                    note="",
                )
                for row in deduction_result["consumption"]
            ]
        )
        db.add_all(
            [
                SalesConsumptionLog(
                    receipt_id=receipt.id,
                    biz_date=use_date,
                    dish_name=row.get("dish_name", ""),
                    ingredient_name=row.get("ingredient_name", ""),
                    ingredient_unit="",
                    required_quantity=None,
                    deducted_quantity=None,
                    shortage_quantity=_to_decimal(row.get("shortage_quantity")),
                    note=row.get("type", "exception"),
                )
                for row in deduction_result["exception_details"]
            ]
        )
        db.commit()
        return {
            "inserted": inserted,
            "skipped": skipped,
            "accumulated": accumulated,
            "sales_results": saved_rows,
            "ticket_consumption": deduction_result["consumption"],
            "remaining_inventory": deduction_result["remaining_inventory"],
            "exception_details": deduction_result["exception_details"],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_purchase_flow(
    *,
    biz_date: str,
    source_image_paths: List[str],
    items: List[ProductItem],
    session_factory: Callable[[], Session],
    llm_adapter: Optional[Any] = None,
) -> dict:
    use_date = parse_biz_date(biz_date)
    inserted = skipped = accumulated = 0
    db = session_factory()
    try:
        source_path = source_image_paths[0] if source_image_paths else ""
        receipt = create_purchase_receipt(db, biz_date=use_date, source_image_path=source_path)
        results: list[dict] = []
        seen_keys: set[str] = set()
        type_by_name: dict[str, str] = {}

        # 分类优先级：本地规则 > BOM 反查 > LLM 兜底
        llm_fallback_names: list[str] = []
        for item in items:
            name_key = normalize_material_name(item.product_name)
            if not name_key or name_key in type_by_name:
                continue
            if match_non_instant_rule(item.product_name):
                type_by_name[name_key] = "non_instant"
                continue
            if exists_in_bom(db, item.product_name):
                type_by_name[name_key] = "instant"
                continue
            llm_fallback_names.append(item.product_name)

        if llm_fallback_names and llm_adapter is not None:
            llm_result = llm_adapter.classify_material_types(llm_fallback_names)
            for raw_name in llm_fallback_names:
                type_by_name.setdefault(normalize_material_name(raw_name), llm_result.get(normalize_material_name(raw_name)))

        for item in items:
            key = "|".join(
                [
                    (item.product_name or "").strip().lower(),
                    "" if item.unit_price is None else str(item.unit_price),
                    "" if item.quantity is None else str(item.quantity),
                    "" if item.unit_amount is None else str(item.unit_amount),
                    (item.quantity_unit or "").strip().lower(),
                ]
            )
            if key in seen_keys:
                skipped += 1
                results.append({"action": "skipped_duplicate_in_request", "item_name": item.product_name})
                continue
            seen_keys.add(key)
            item_type = type_by_name.get(normalize_material_name(item.product_name))
            action, row = upsert_purchase_item(
                db,
                receipt_id=receipt.id,
                biz_date=use_date,
                item=item,
                consumption_type=item_type,
            )
            logger.info("purchase.save item=%s action=%s biz_date=%s", row.item_name, action, use_date.isoformat())
            if action == "inserted":
                inserted += 1
            elif action == "skipped":
                skipped += 1
            else:
                accumulated += 1
            results.append({"action": action, "item_name": row.item_name, "id": row.id, "consumption_type": row.consumption_type})
        db.commit()
        logger.info(
            "purchase.save done: biz_date=%s inserted=%s skipped=%s accumulated=%s receipt_id=%s",
            use_date.isoformat(),
            inserted,
            skipped,
            accumulated,
            receipt.id,
        )
        return {"inserted": inserted, "skipped": skipped, "accumulated": accumulated, "results": results}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_sales_flow(
    *,
    biz_date: str,
    source_image_paths: List[str],
    items: List[SalesLineItem],
    session_factory: Callable[[], Session],
) -> dict:
    use_date = parse_biz_date(biz_date)
    inserted = skipped = accumulated = 0
    db = session_factory()
    try:
        source_path = source_image_paths[0] if source_image_paths else ""
        receipt = create_sales_receipt(db, biz_date=use_date, source_image_path=source_path)
        results: list[dict] = []
        for item in items:
            action, row = upsert_sales_item(db, receipt_id=receipt.id, biz_date=use_date, item=item)
            logger.info("sales.save item=%s action=%s biz_date=%s", row.item_name, action, use_date.isoformat())
            if action == "inserted":
                inserted += 1
            elif action == "skipped":
                skipped += 1
            else:
                accumulated += 1
            results.append({"action": action, "item_name": row.item_name, "id": row.id})
        db.commit()
        logger.info(
            "sales.save done: biz_date=%s inserted=%s skipped=%s accumulated=%s receipt_id=%s",
            use_date.isoformat(),
            inserted,
            skipped,
            accumulated,
            receipt.id,
        )
        return {"inserted": inserted, "skipped": skipped, "accumulated": accumulated, "results": results}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
