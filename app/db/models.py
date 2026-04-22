from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProductRecord(Base):
    __tablename__ = "product_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Dedup dimensions
    product_name: Mapped[str] = mapped_column(String(512), default="")
    unit_price: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    unit_amount: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    quantity_unit: Mapped[str] = mapped_column(String(32), default="")

    # Aggregated fields
    total_quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    amount: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)

    remarks: Mapped[str] = mapped_column(String(2048), default="")

    # Business date rule: same-day skip, cross-day accumulate.
    last_saved_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PurchaseReceipt(Base):
    __tablename__ = "purchase_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    biz_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_image_path: Mapped[str] = mapped_column(String(1024), default="")
    raw_llm_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PurchaseItem(Base):
    __tablename__ = "purchase_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("purchase_receipts.id"), nullable=False, index=True)

    item_name: Mapped[str] = mapped_column(String(512), default="")
    quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    unit_amount: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    quantity_unit: Mapped[str] = mapped_column(String(32), default="")
    total_quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    unit_price: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    amount: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    remarks: Mapped[str] = mapped_column(String(2048), default="")
    # instant: 即时消耗, non_instant: 非即时消耗, null: 待分类
    consumption_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    low_stock_alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    low_stock_threshold: Mapped[Optional[object]] = mapped_column(Numeric(18, 6), nullable=True)
    low_stock_last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True, unique=True)
    last_saved_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SalesReceipt(Base):
    __tablename__ = "sales_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    biz_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_image_path: Mapped[str] = mapped_column(String(1024), default="")
    raw_llm_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalesItem(Base):
    __tablename__ = "sales_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("sales_receipts.id"), nullable=False, index=True)

    item_name: Mapped[str] = mapped_column(String(512), default="")
    quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    unit_price: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    amount: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    remarks: Mapped[str] = mapped_column(String(2048), default="")

    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True, unique=True)
    last_saved_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    biz_date: Mapped[date] = mapped_column(Date, primary_key=True)
    revenue_total: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    purchase_total: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    gross_profit: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    notes: Mapped[str] = mapped_column(String(2048), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BomIngredient(Base):
    __tablename__ = "bom_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dish_name: Mapped[str] = mapped_column(String(512), default="", index=True)
    ingredient_name: Mapped[str] = mapped_column(String(512), default="", index=True)
    ingredient_unit: Mapped[str] = mapped_column(String(32), default="")
    ingredient_amount: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalesConsumptionLog(Base):
    __tablename__ = "sales_consumption_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("sales_receipts.id"), nullable=False, index=True)
    biz_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    dish_name: Mapped[str] = mapped_column(String(512), default="", index=True)
    ingredient_name: Mapped[str] = mapped_column(String(512), default="", index=True)
    ingredient_unit: Mapped[str] = mapped_column(String(32), default="")
    required_quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    deducted_quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    shortage_quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=True)
    note: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

