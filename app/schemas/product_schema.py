from decimal import Decimal
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


UNIT_ALIASES = {
    "公斤": "kg",
    "千克": "kg",
    "kg": "kg",
    "g": "g",
    "克": "g",
    "斤": "斤",
    "两": "两",
    "个": "个",
    "只": "只",
    "包": "袋",
    "袋": "袋",
    "箱": "箱",
    "瓶": "瓶",
    "盒": "盒",
}


class ProductItem(BaseModel):
    product_name: str = Field(default="", description="Product name")
    unit_price: Optional[Decimal] = Field(default=None, description="Unit price")
    quantity: Optional[Decimal] = Field(default=None, description="Purchase count")
    unit_amount: Optional[Decimal] = Field(default=None, description="Amount per purchase unit")
    quantity_unit: str = Field(default="", description="Quantity unit, e.g. 斤/个/kg/袋")
    total_quantity: Optional[Decimal] = Field(default=None, description="quantity * unit_amount")
    amount: Optional[Decimal] = Field(default=None, description="Amount")
    order_created_at: datetime = Field(description="Order created time, defaults to upload time")
    remarks: str = Field(default="", description="Remarks")

    @field_validator("unit_price", "quantity", "unit_amount", "total_quantity", "amount", mode="before")
    @classmethod
    def normalize_decimal(cls, value: object) -> Optional[Decimal]:
        if value in ("", None):
            return None
        try:
            return Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"Invalid numeric value: {value}") from exc

    @field_validator("quantity_unit", mode="before")
    @classmethod
    def normalize_quantity_unit(cls, value: object) -> str:
        if value in ("", None):
            return ""
        unit = str(value).strip().lower()
        return UNIT_ALIASES.get(unit, str(value).strip())

    @model_validator(mode="after")
    def compute_amount(self) -> "ProductItem":
        if self.amount is None and self.unit_price is not None and self.quantity is not None:
            self.amount = self.unit_price * self.quantity
        if self.total_quantity is None and self.quantity is not None and self.unit_amount is not None:
            self.total_quantity = self.quantity * self.unit_amount
        return self


class ParseResult(BaseModel):
    success: bool
    item: Optional[ProductItem] = None
    items: List[ProductItem] = Field(default_factory=list)
    error: str = ""
