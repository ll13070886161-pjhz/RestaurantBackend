from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional
import logging
import requests

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.schemas.product_schema import ProductItem
from app.schemas.sales_schema import SalesLineItem
from app.services.excel_writer import write_daily_report_excel, write_items_to_excel
from app.services.llm_adapter import LLMAdapter
from app.services.material_classification import exists_in_bom, match_non_instant_rule, normalize_material_name
from app.services.workflow_service import (
    is_empty_product_item,
    parse_biz_date,
    parse_purchase_images_flow,
    parse_sales_images_flow,
    process_sales_and_deduct_flow,
    save_sales_flow,
    save_purchase_flow,
    suggest_dish_names,
)
from app.db.session import SessionLocal
from app.db.crud import save_item
from app.db.models import BomIngredient, ProductRecord, PurchaseItem, SalesConsumptionLog, SalesItem


router = APIRouter()
llm_adapter = LLMAdapter()
logger = logging.getLogger(__name__)

# Keep latest generated report path for download endpoint.
LATEST_REPORT_PATH: Optional[Path] = None
PURCHASE_LATEST_REPORT_PATH: Optional[Path] = None
SALES_LATEST_REPORT_PATH: Optional[Path] = None


PREVIEW_COLUMNS = [
    {"key": "product_name", "label": "商品名称"},
    {"key": "unit_price", "label": "商品单价"},
    {"key": "quantity", "label": "购买份数"},
    {"key": "unit_amount", "label": "单份数量"},
    {"key": "quantity_unit", "label": "量词"},
    {"key": "total_quantity", "label": "总数量"},
    {"key": "amount", "label": "商品金额"},
    {"key": "order_created_at", "label": "订单生成时间"},
    {"key": "remarks", "label": "备注"},
]

PURCHASE_COLUMNS = [
    {"key": "product_name", "label": "用料/商品名称"},
    {"key": "unit_price", "label": "单价"},
    {"key": "quantity", "label": "购买份数"},
    {"key": "unit_amount", "label": "单份数量"},
    {"key": "quantity_unit", "label": "量词"},
    {"key": "total_quantity", "label": "总数量"},
    {"key": "amount", "label": "金额"},
    {"key": "consumption_type", "label": "消耗类型"},
    {"key": "order_created_at", "label": "识别时间"},
    {"key": "remarks", "label": "备注"},
]

SALES_COLUMNS = [
    {"key": "item_name", "label": "项目/菜品名称"},
    {"key": "quantity", "label": "数量"},
    {"key": "unit_price", "label": "单价"},
    {"key": "amount", "label": "金额"},
    {"key": "order_created_at", "label": "识别时间"},
    {"key": "remarks", "label": "备注"},
]


class SaveItemsRequest(BaseModel):
    items: List[ProductItem] = Field(default_factory=list)


def _record_to_dict(rec: ProductRecord) -> dict:
    return {
        "id": rec.id,
        "product_name": rec.product_name,
        "unit_price": rec.unit_price,
        "quantity": rec.quantity,
        "unit_amount": rec.unit_amount,
        "quantity_unit": rec.quantity_unit,
        "total_quantity": rec.total_quantity,
        "amount": rec.amount,
        "remarks": rec.remarks,
        "last_saved_date": rec.last_saved_date.isoformat(),
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def _consumption_type_label(value: Optional[str]) -> str:
    if value == "instant":
        return "即时消耗"
    if value == "non_instant":
        return "非即时消耗"
    return "待分类"


class SavePurchaseRequest(BaseModel):
    biz_date: str = ""
    source_image_paths: List[str] = Field(default_factory=list)
    items: List[ProductItem] = Field(default_factory=list)


class SaveSalesRequest(BaseModel):
    biz_date: str = ""
    source_image_paths: List[str] = Field(default_factory=list)
    items: List[SalesLineItem] = Field(default_factory=list)


class ReclassifyPurchaseRequest(BaseModel):
    include_classified: bool = False
    limit: int = 2000


class BomItemPayload(BaseModel):
    dish_name: str
    ingredient_name: str
    ingredient_unit: str = ""
    ingredient_amount: Optional[float] = None


class SaveBomRequest(BaseModel):
    items: List[BomItemPayload] = Field(default_factory=list)


class ConfirmSalesSaveRequest(BaseModel):
    biz_date: str = ""
    source_image_paths: List[str] = Field(default_factory=list)
    items: List[SalesLineItem] = Field(default_factory=list)
    confirmed: bool = False


def _to_float(value: object) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _dedup_key(item: ProductItem) -> tuple[str, str, str, str, str]:
    name = (item.product_name or "").strip().lower()
    unit_price = "" if item.unit_price is None else str(item.unit_price)
    quantity = "" if item.quantity is None else str(item.quantity)
    unit_amount = "" if item.unit_amount is None else str(item.unit_amount)
    quantity_unit = (item.quantity_unit or "").strip().lower()
    return (name, unit_price, quantity, unit_amount, quantity_unit)


def _require_local_write(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if client_host not in settings.write_allowed_ips:
        raise HTTPException(status_code=403, detail="Database write is not allowed from this client.")


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


@router.get("/api/purchase/items")
def list_purchase_items(limit: int = 1000, offset: int = 0) -> dict:
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)
    with SessionLocal() as session:
        rows = (
            session.execute(
                select(PurchaseItem)
                .order_by(PurchaseItem.updated_at.desc(), PurchaseItem.id.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )

    return {
        "items": [
            {
                "id": row.id,
                "receipt_id": row.receipt_id,
                "item_name": row.item_name,
                "quantity": float(row.quantity) if row.quantity is not None else None,
                "unit_amount": float(row.unit_amount) if row.unit_amount is not None else None,
                "quantity_unit": row.quantity_unit,
                "total_quantity": float(row.total_quantity) if row.total_quantity is not None else None,
                "unit_price": float(row.unit_price) if row.unit_price is not None else None,
                "amount": float(row.amount) if row.amount is not None else None,
                "remarks": row.remarks,
                "consumption_type": row.consumption_type or "unknown",
                "consumption_type_label": _consumption_type_label(row.consumption_type),
                "low_stock_alert_enabled": bool(row.low_stock_alert_enabled),
                "low_stock_threshold": float(row.low_stock_threshold) if row.low_stock_threshold is not None else None,
                "low_stock_last_notified_at": (
                    row.low_stock_last_notified_at.isoformat() if row.low_stock_last_notified_at else None
                ),
                "last_saved_date": row.last_saved_date.isoformat() if row.last_saved_date else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
        "limit": limit,
        "offset": offset,
    }


class UpdatePurchaseItemTypeRequest(BaseModel):
    consumption_type: Optional[str] = None  # instant | non_instant | unknown | null


class UpdatePurchaseItemAlertRequest(BaseModel):
    enabled: bool = False
    threshold: Optional[float] = None


def _alert_item_to_dict(row: PurchaseItem) -> dict:
    current_stock = float(row.total_quantity) if row.total_quantity is not None else 0.0
    threshold = float(row.low_stock_threshold) if row.low_stock_threshold is not None else 0.0
    shortage = max(0.0, threshold - current_stock)
    return {
        "id": row.id,
        "item_name": row.item_name,
        "quantity_unit": row.quantity_unit,
        "current_stock": current_stock,
        "threshold": threshold,
        "shortage": shortage,
        "last_saved_date": row.last_saved_date.isoformat() if row.last_saved_date else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _post_to_openclaw(items: list[dict]) -> dict:
    webhook = settings.inventory_alert_openclaw_webhook_url
    if not webhook:
        return {"sent": False, "channel": "openclaw", "reason": "INVENTORY_ALERT_OPENCLAW_WEBHOOK_URL is empty"}

    payload = {
        "event": "inventory_low_stock_alert",
        "source": settings.app_name,
        "items": items,
        "message": f"库存预警：共 {len(items)} 个物料低于阈值",
    }
    resp = requests.post(webhook, json=payload, timeout=8)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"OpenClaw notification failed: HTTP {resp.status_code}")
    logger.info("inventory alert sent to openclaw, status=%s", resp.status_code)
    return {"sent": True, "channel": "openclaw"}


def _post_to_feishu(items: list[dict]) -> dict:
    webhook = settings.inventory_alert_feishu_webhook_url
    if not webhook:
        return {"sent": False, "channel": "feishu", "reason": "INVENTORY_ALERT_FEISHU_WEBHOOK_URL is empty"}

    lines = ["【库存预警】以下物料低于阈值："]
    for item in items[:20]:
        unit = item["quantity_unit"] or ""
        lines.append(
            f"- {item['item_name']}：库存 {item['current_stock']}{unit}，阈值 {item['threshold']}{unit}，缺口 {item['shortage']}{unit}"
        )
    if len(items) > 20:
        lines.append(f"... 其余 {len(items) - 20} 个物料请登录后台查看。")

    payload = {
        "msg_type": "text",
        "content": {"text": "\n".join(lines)},
    }
    resp = requests.post(webhook, json=payload, timeout=8)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Feishu notification failed: HTTP {resp.status_code}")
    # Feishu bot webhook returns HTTP 200 even on logical failures.
    try:
        body = resp.json()
    except Exception:
        body = None
    if isinstance(body, dict) and body.get("code", 0) != 0:
        raise HTTPException(status_code=502, detail=f"Feishu notification rejected: {body}")
    logger.info("inventory alert sent to feishu, status=%s, body=%s", resp.status_code, body)
    return {"sent": True, "channel": "feishu"}


@router.post("/api/purchase/items/{item_id}/consumption-type")
def update_purchase_item_consumption_type(
    item_id: int,
    payload: UpdatePurchaseItemTypeRequest,
    request: Request,
) -> dict:
    _require_local_write(request)

    raw = (payload.consumption_type or "").strip().lower()
    if raw in ("", "unknown", "null", "none"):
        new_value: Optional[str] = None
    elif raw in ("instant", "non_instant"):
        new_value = raw
    else:
        raise HTTPException(status_code=422, detail="Invalid consumption_type. Use instant | non_instant | unknown.")

    with SessionLocal() as session:
        row = session.get(PurchaseItem, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Purchase item not found.")
        row.consumption_type = new_value
        session.commit()
        session.refresh(row)

    return {
        "success": True,
        "item": {
            "id": row.id,
            "receipt_id": row.receipt_id,
            "item_name": row.item_name,
            "quantity": float(row.quantity) if row.quantity is not None else None,
            "unit_amount": float(row.unit_amount) if row.unit_amount is not None else None,
            "quantity_unit": row.quantity_unit,
            "total_quantity": float(row.total_quantity) if row.total_quantity is not None else None,
            "unit_price": float(row.unit_price) if row.unit_price is not None else None,
            "amount": float(row.amount) if row.amount is not None else None,
            "remarks": row.remarks,
            "consumption_type": row.consumption_type or "unknown",
            "consumption_type_label": _consumption_type_label(row.consumption_type),
            "low_stock_alert_enabled": bool(row.low_stock_alert_enabled),
            "low_stock_threshold": float(row.low_stock_threshold) if row.low_stock_threshold is not None else None,
            "low_stock_last_notified_at": (
                row.low_stock_last_notified_at.isoformat() if row.low_stock_last_notified_at else None
            ),
            "last_saved_date": row.last_saved_date.isoformat() if row.last_saved_date else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    }


@router.post("/api/purchase/items/{item_id}/alert-config")
def update_purchase_item_alert_config(
    item_id: int,
    payload: UpdatePurchaseItemAlertRequest,
    request: Request,
) -> dict:
    _require_local_write(request)
    threshold_value = None if payload.threshold is None else max(0.0, float(payload.threshold))
    with SessionLocal() as session:
        row = session.get(PurchaseItem, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Purchase item not found.")
        row.low_stock_alert_enabled = bool(payload.enabled)
        row.low_stock_threshold = Decimal(str(threshold_value)) if threshold_value is not None else None
        session.commit()
        session.refresh(row)
    return {
        "success": True,
        "item": {
            "id": row.id,
            "item_name": row.item_name,
            "low_stock_alert_enabled": bool(row.low_stock_alert_enabled),
            "low_stock_threshold": float(row.low_stock_threshold) if row.low_stock_threshold is not None else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    }


@router.get("/api/inventory/alerts")
def list_low_stock_alerts(trigger_notify: bool = False) -> dict:
    with SessionLocal() as session:
        rows = (
            session.execute(
                select(PurchaseItem).where(
                    PurchaseItem.low_stock_alert_enabled.is_(True),
                    PurchaseItem.low_stock_threshold.is_not(None),
                    PurchaseItem.total_quantity.is_not(None),
                    PurchaseItem.total_quantity < PurchaseItem.low_stock_threshold,
                )
            )
            .scalars()
            .all()
        )
        items = [_alert_item_to_dict(row) for row in rows]
        if trigger_notify and items:
            for row in rows:
                row.low_stock_last_notified_at = datetime.utcnow()
            session.commit()

    notification_results: list[dict] = []
    if trigger_notify and items:
        if settings.inventory_alert_openclaw_enabled:
            notification_results.append(_post_to_openclaw(items))
        else:
            notification_results.append({"sent": False, "channel": "openclaw", "reason": "INVENTORY_ALERT_OPENCLAW_ENABLED=false"})
        if settings.inventory_alert_feishu_webhook_url:
            notification_results.append(_post_to_feishu(items))
        else:
            notification_results.append(
                {"sent": False, "channel": "feishu", "reason": "INVENTORY_ALERT_FEISHU_WEBHOOK_URL is empty"}
            )

    sent_count = sum(1 for item in notification_results if item.get("sent"))

    return {
        "count": len(items),
        "items": items,
        "popup_enabled": settings.inventory_alert_popup_enabled,
        "notify_results": notification_results,
        "notify_sent_count": sent_count,
    }


@router.post("/api/parse-images")
async def parse_images(files: List[UploadFile] = File(...)) -> dict:
    global LATEST_REPORT_PATH
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    items: List[ProductItem] = []
    errors: list[dict] = []
    seen_keys: set[tuple[str, str, str, str, str]] = set()

    for file in files:
        content = await file.read()
        if not content:
            errors.append({"file": file.filename, "error": "Empty file"})
            continue
        result = llm_adapter.parse_product_from_image(
            image_bytes=content,
            upload_time=datetime.now(),
        )
        if result.success:
            parsed_items = result.items if result.items else ([result.item] if result.item else [])
            valid_items: List[ProductItem] = []
            for item in parsed_items:
                if is_empty_product_item(item):
                    continue
                key = _dedup_key(item)
                if key in seen_keys:
                    logger.info("Skip duplicated item from file=%s, product=%s", file.filename, item.product_name)
                    continue
                seen_keys.add(key)
                valid_items.append(item)
            if not valid_items:
                errors.append({"file": file.filename, "error": "LLM returned empty fields for this image."})
                logger.warning("Skip empty LLM result: file=%s", file.filename)
                continue
            items.extend(valid_items)
            logger.info("Accepted %s items from file=%s", len(valid_items), file.filename)
        else:
            errors.append({"file": file.filename, "error": result.error})

    if not items and errors:
        raise HTTPException(status_code=422, detail={"message": "All files failed.", "errors": errors})

    LATEST_REPORT_PATH = write_items_to_excel(items, settings.output_dir)
    return {
        "success_count": len(items),
        "error_count": len(errors),
        "errors": errors,
        "report_file": LATEST_REPORT_PATH.name,
        "preview_columns": PREVIEW_COLUMNS,
        "preview": [item.model_dump(mode="json") for item in items],
    }


# 添加下载端点
@router.get("/api/download/{filename}")
def download_file(filename: str, request: Request):
    """下载生成的Excel文件"""
    file_path = settings.output_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 记录下载请求
    client_ip = request.client.host if request.client else "unknown"
    logger.info("文件下载: filename=%s, client_ip=%s", filename, client_ip)
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/api/download-latest")
def download_latest_report(request: Request):
    """下载最新生成的报告"""
    global LATEST_REPORT_PATH, PURCHASE_LATEST_REPORT_PATH, SALES_LATEST_REPORT_PATH
    
    # 优先返回采购报告，然后是销售报告，最后是通用报告
    target_path = None
    report_type = "未知"
    
    if PURCHASE_LATEST_REPORT_PATH and PURCHASE_LATEST_REPORT_PATH.exists():
        target_path = PURCHASE_LATEST_REPORT_PATH
        report_type = "采购"
    elif SALES_LATEST_REPORT_PATH and SALES_LATEST_REPORT_PATH.exists():
        target_path = SALES_LATEST_REPORT_PATH
        report_type = "销售"
    elif LATEST_REPORT_PATH and LATEST_REPORT_PATH.exists():
        target_path = LATEST_REPORT_PATH
        report_type = "通用"
    
    if not target_path:
        raise HTTPException(status_code=404, detail="没有可用的报告文件")
    
    client_ip = request.client.host if request.client else "unknown"
    logger.info("下载最新%s报告: filename=%s, client_ip=%s", report_type, target_path.name, client_ip)
    
    return FileResponse(
        path=target_path,
        filename=target_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
