from datetime import datetime
from decimal import Decimal

from app.db.models import BomIngredient, PurchaseItem
from app.schemas.product_schema import ProductItem
from app.services.workflow_service import save_purchase_flow
from tests.conftest import create_test_session


class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


class _FakeLLMAdapter:
    def classify_material_types(self, names):
        return {str(name).strip().lower(): "instant" for name in names}


def test_save_purchase_flow_classification_priority():
    session = create_test_session()
    try:
        session.add(BomIngredient(dish_name="宫保鸡丁", ingredient_name="鸡腿肉", ingredient_unit="kg"))
        session.commit()

        items = [
            ProductItem(
                product_name="打包盒",
                unit_price=Decimal("1"),
                quantity=Decimal("10"),
                unit_amount=Decimal("1"),
                quantity_unit="盒",
                amount=Decimal("10"),
                order_created_at=datetime.now(),
            ),
            ProductItem(
                product_name="鸡腿肉",
                unit_price=Decimal("20"),
                quantity=Decimal("2"),
                unit_amount=Decimal("1"),
                quantity_unit="kg",
                amount=Decimal("40"),
                order_created_at=datetime.now(),
            ),
            ProductItem(
                product_name="冰淇淋脆筒",
                unit_price=Decimal("2"),
                quantity=Decimal("5"),
                unit_amount=Decimal("1"),
                quantity_unit="个",
                amount=Decimal("10"),
                order_created_at=datetime.now(),
            ),
        ]

        save_purchase_flow(
            biz_date="2026-04-21",
            source_image_paths=[],
            items=items,
            session_factory=_FakeSessionFactory(session),
            llm_adapter=_FakeLLMAdapter(),
        )

        rows = session.query(PurchaseItem).all()
        mapping = {r.item_name: r.consumption_type for r in rows}
        assert mapping["打包盒"] == "non_instant"
        assert mapping["鸡腿肉"] == "instant"
        assert mapping["冰淇淋脆筒"] == "instant"
    finally:
        session.close()
