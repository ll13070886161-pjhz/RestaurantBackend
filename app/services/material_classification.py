from __future__ import annotations

from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BomIngredient

NON_INSTANT_KEYWORDS = [
    "杯",
    "盒",
    "签",
    "纸",
    "手套",
    "洗洁精",
    "清洁剂",
    "抹布",
    "围裙",
    "厨师服",
    "碗",
    "盘",
    "筷子",
    "勺子",
    "锡纸",
    "保鲜膜",
    "垃圾袋",
    "牙签",
    "餐巾纸",
]

MATERIAL_CLASSIFICATION_SYSTEM_PROMPT = """
你是一名专业的餐饮供应链数据标注专家，精通后厨库存管理与成本核算逻辑。

请根据输入的物料名称列表，将其分为两类：

即时消耗用料：原材料、调料、半成品，用于制作菜品本体，且随菜品销量按配方比例从库存中扣除，直接影响菜品成本。

非即时消耗用料：餐具、包装耗材、工具、清洁用品、固定资产。即使它们会随订单使用而数量减少，也不随菜品配方自动扣减，而是通过盘点或费用摊销处理。

分类规则：

判断依据是该物料是否出现在《标准菜品配方表》中。

食用油、酱油、面粉等虽不是每单精确计量，但属于成本核算范围内的即时消耗。

所有盛器（杯子、碗、竹签、锡纸盒）除非是菜品可食用部分，否则均为非即时消耗。

参考示例：
五花肉 → 即时消耗（菜品主料）
生抽酱油 → 即时消耗（调味品）
打包盒 → 非即时消耗（包装耗材）
竹签 → 非即时消耗（工具类）
一次性手套 → 非即时消耗（低值易耗品）
冰淇淋脆筒 → 即时消耗（可食用部分且为配方成分）

输出格式：仅输出严格 JSON 数组，不含 Markdown 标记。
格式：[{"name": "物料名", "type": "即时消耗/非即时消耗"}]
""".strip()


def normalize_material_name(name: str) -> str:
    return (name or "").strip().lower()


def match_non_instant_rule(name: str) -> bool:
    clean_name = normalize_material_name(name)
    return any(keyword in clean_name for keyword in NON_INSTANT_KEYWORDS)


def exists_in_bom(session: Session, name: str) -> bool:
    clean_name = normalize_material_name(name)
    if not clean_name:
        return False
    stmt = select(BomIngredient.id).where(func.lower(BomIngredient.ingredient_name) == clean_name).limit(1)
    return session.execute(stmt).first() is not None


def build_llm_material_classification_user_prompt(names: Iterable[str]) -> str:
    rows = [f"- {n}" for n in names if (n or "").strip()]
    return "请分类以下物料名称：\n" + "\n".join(rows)
