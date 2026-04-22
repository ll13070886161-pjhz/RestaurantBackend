from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SalesLineItem(BaseModel):
    item_name: str = Field(default="", description="Dish or item name")
    quantity: Optional[Decimal] = Field(default=None, description="Quantity sold")
    unit_price: Optional[Decimal] = Field(default=None, description="Unit price")
    amount: Optional[Decimal] = Field(default=None, description="Line total amount")
    order_created_at: datetime = Field(description="Time, defaults to upload time")
    remarks: str = Field(default="", description="Remarks")

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def normalize_decimal(cls, value: object) -> Optional[Decimal]:
        if value in ("", None):
            return None
        try:
            return Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"Invalid numeric value: {value}") from exc

    @model_validator(mode="after")
    def compute_amount(self) -> "SalesLineItem":
        if self.amount is None and self.unit_price is not None and self.quantity is not None:
            self.amount = self.unit_price * self.quantity
        return self

