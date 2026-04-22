from datetime import datetime
from decimal import Decimal

from app.db.crud import save_item
from app.db.models import PurchaseItem, SalesItem
from app.schemas.product_schema import ProductItem
from tests.conftest import create_test_session


def test_save_item_insert_then_skip_same_day():
    session = create_test_session()
    try:
        today = datetime(2026, 4, 20).date()
        item = ProductItem(
            product_name="豆腐",
            unit_price=Decimal("4"),
            quantity=Decimal("2"),
            unit_amount=Decimal("1"),
            quantity_unit="盒",
            amount=Decimal("8"),
            total_quantity=Decimal("2"),
            order_created_at=datetime.now(),
        )

        action1, _ = save_item(session, item, today=today)
        action2, _ = save_item(session, item, today=today)

        assert action1 == "inserted"
        assert action2 == "skipped"
    finally:
        session.close()


def test_save_item_accumulate_cross_day():
    session = create_test_session()
    try:
        day1 = datetime(2026, 4, 20).date()
        day2 = datetime(2026, 4, 21).date()
        item = ProductItem(
            product_name="鸡蛋",
            unit_price=Decimal("1"),
            quantity=Decimal("10"),
            unit_amount=Decimal("1"),
            quantity_unit="个",
            amount=Decimal("10"),
            total_quantity=Decimal("10"),
            order_created_at=datetime.now(),
        )

        save_item(session, item, today=day1)
        action, row = save_item(session, item, today=day2)

        assert action == "accumulated"
        assert row.amount == Decimal("20")
        assert row.total_quantity == Decimal("20")
        assert row.quantity == Decimal("20")
    finally:
        session.close()


def test_daily_totals_formula_matches_report_logic():
    session = create_test_session()
    try:
        use_date = datetime(2026, 4, 20).date()
        session.add_all(
            [
                PurchaseItem(
                    receipt_id=1,
                    item_name="牛肉",
                    quantity=Decimal("2"),
                    unit_amount=Decimal("1"),
                    quantity_unit="kg",
                    total_quantity=Decimal("2"),
                    unit_price=Decimal("40"),
                    amount=Decimal("80"),
                    remarks="",
                    dedup_key="beef",
                    last_saved_date=use_date,
                ),
                PurchaseItem(
                    receipt_id=1,
                    item_name="青椒",
                    quantity=Decimal("3"),
                    unit_amount=Decimal("1"),
                    quantity_unit="kg",
                    total_quantity=Decimal("3"),
                    unit_price=Decimal("5"),
                    amount=Decimal("15"),
                    remarks="",
                    dedup_key="pepper",
                    last_saved_date=use_date,
                ),
                SalesItem(
                    receipt_id=1,
                    item_name="卤肉饭",
                    quantity=Decimal("5"),
                    unit_price=Decimal("20"),
                    amount=Decimal("100"),
                    remarks="",
                    dedup_key="rice",
                    last_saved_date=use_date,
                ),
            ]
        )
        session.commit()

        purchase_rows = session.query(PurchaseItem).filter(PurchaseItem.last_saved_date == use_date).all()
        sales_rows = session.query(SalesItem).filter(SalesItem.last_saved_date == use_date).all()

        purchase_total = sum([float(r.amount or 0) for r in purchase_rows]) if purchase_rows else 0.0
        revenue_total = sum([float(r.amount or 0) for r in sales_rows]) if sales_rows else 0.0

        assert purchase_total == 95.0
        assert revenue_total == 100.0
    finally:
        session.close()
