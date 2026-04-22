from datetime import datetime
from decimal import Decimal

from app.db.domain_crud import (
    create_purchase_receipt,
    create_sales_receipt,
    upsert_purchase_item,
    upsert_sales_item,
)
from app.schemas.product_schema import ProductItem
from app.schemas.sales_schema import SalesLineItem
from tests.conftest import create_test_session


def test_upsert_purchase_item_insert_and_skip_same_day():
    session = create_test_session()
    try:
        use_date = datetime(2026, 4, 20).date()
        receipt = create_purchase_receipt(session, biz_date=use_date, source_image_path="a.jpg")
        item = ProductItem(
            product_name="牛肉",
            unit_price=Decimal("40"),
            quantity=Decimal("2"),
            unit_amount=Decimal("1"),
            quantity_unit="kg",
            amount=Decimal("80"),
            order_created_at=datetime.now(),
        )

        action1, row1 = upsert_purchase_item(session, receipt_id=receipt.id, biz_date=use_date, item=item)
        action2, row2 = upsert_purchase_item(session, receipt_id=receipt.id, biz_date=use_date, item=item)

        assert action1 == "inserted"
        assert action2 == "skipped"
        assert row1.id == row2.id
    finally:
        session.close()


def test_upsert_purchase_item_accumulates_cross_day():
    session = create_test_session()
    try:
        day1 = datetime(2026, 4, 20).date()
        day2 = datetime(2026, 4, 21).date()
        receipt1 = create_purchase_receipt(session, biz_date=day1, source_image_path="a.jpg")
        receipt2 = create_purchase_receipt(session, biz_date=day2, source_image_path="b.jpg")
        item = ProductItem(
            product_name="青椒",
            unit_price=Decimal("5"),
            quantity=Decimal("2"),
            unit_amount=Decimal("1"),
            quantity_unit="kg",
            amount=Decimal("10"),
            total_quantity=Decimal("2"),
            order_created_at=datetime.now(),
        )

        upsert_purchase_item(session, receipt_id=receipt1.id, biz_date=day1, item=item)
        action, row = upsert_purchase_item(session, receipt_id=receipt2.id, biz_date=day2, item=item)

        assert action == "accumulated"
        assert row.amount == Decimal("20")
        assert row.quantity == Decimal("4")
        assert row.total_quantity == Decimal("4")
        assert row.last_saved_date == day2
    finally:
        session.close()


def test_upsert_sales_item_insert_skip_accumulate():
    session = create_test_session()
    try:
        day1 = datetime(2026, 4, 20).date()
        day2 = datetime(2026, 4, 21).date()
        receipt1 = create_sales_receipt(session, biz_date=day1, source_image_path="a.jpg")
        receipt2 = create_sales_receipt(session, biz_date=day2, source_image_path="b.jpg")
        item = SalesLineItem(
            item_name="卤肉饭",
            quantity=Decimal("1"),
            unit_price=Decimal("20"),
            amount=Decimal("20"),
            order_created_at=datetime.now(),
        )

        action1, _ = upsert_sales_item(session, receipt_id=receipt1.id, biz_date=day1, item=item)
        action2, row2 = upsert_sales_item(session, receipt_id=receipt1.id, biz_date=day1, item=item)
        action3, row3 = upsert_sales_item(session, receipt_id=receipt2.id, biz_date=day2, item=item)

        assert action1 == "inserted"
        assert action2 == "skipped"
        assert action3 == "accumulated"
        assert row2.id == row3.id
        assert row3.amount == Decimal("40")
        assert row3.quantity == Decimal("2")
    finally:
        session.close()
