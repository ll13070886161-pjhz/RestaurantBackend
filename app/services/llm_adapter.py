import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

from app.core.config import settings
from app.schemas.product_schema import ProductItem, ParseResult
from app.schemas.sales_schema import SalesLineItem
from app.services.material_classification import (
    MATERIAL_CLASSIFICATION_SYSTEM_PROMPT,
    build_llm_material_classification_user_prompt,
)
from app.services.provider_other import OtherProviderClient


logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """
你是商品信息提取助手。请仅根据图片内容提取信息，不要臆造。
输出必须是 JSON，支持两种格式：
1) {"items": [ ... ]}，推荐
2) [ ... ]
其中每个元素字段严格如下：
product_name, unit_price, quantity, unit_amount, quantity_unit, total_quantity, amount, remarks

规则：
1) 无法识别的字段使用空字符串（数值字段使用 null）。
2) 数值字段必须是数字或 null，不要带货币符号。
3) quantity 表示购买份数（例如右侧 + - 的件数）。
4) unit_amount 表示单份数量（如 0.5、1、2.5）。
5) quantity_unit 表示量词（如 斤、个、kg、袋）。尽量输出标准量词：
   - 公斤/千克 -> kg
   - 克 -> g
   - 包 -> 袋
6) total_quantity = quantity * unit_amount；若缺失可填 null。
7) 一张图可能有多条商品，请尽量提取所有可见商品。
8) 不要输出任何 JSON 之外的文字。
"""


SALES_PROMPT_TEMPLATE = """
你是营业小票信息提取助手。请仅根据图片内容提取信息，不要臆造。
输出必须是 JSON，支持两种格式：
1) {"items": [ ... ]}，推荐
2) [ ... ]
其中每个元素字段严格如下：
item_name, quantity, unit_price, amount, remarks

规则：
1) 无法识别的字段使用空字符串（数值字段使用 null）。
2) 数值字段必须是数字或 null，不要带货币符号。
3) 一张小票可能有多行项目，请尽量提取所有可见行。
4) 不要输出任何 JSON 之外的文字。
"""


def _extract_json_text(raw_content: str) -> str:
    fenced = re.search(r"```json\s*([\{\[].*?[\}\]])\s*```", raw_content, re.S)
    if fenced:
        return fenced.group(1)

    # Fallback: find the first complete JSON object/array by bracket matching.
    obj_start = raw_content.find("{")
    arr_start = raw_content.find("[")
    starts = [idx for idx in (obj_start, arr_start) if idx != -1]
    first_start = min(starts) if starts else -1
    if first_start != -1:
        open_ch = raw_content[first_start]
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for idx in range(first_start, len(raw_content)):
            ch = raw_content[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return raw_content[first_start : idx + 1]

    last_obj = raw_content.rfind("}")
    if obj_start != -1 and last_obj != -1 and last_obj > obj_start:
        return raw_content[obj_start:last_obj + 1]

    last_arr = raw_content.rfind("]")
    if arr_start != -1 and last_arr != -1 and last_arr > arr_start:
        return raw_content[arr_start:last_arr + 1]
    return raw_content


class LLMAdapter:
    def __init__(self) -> None:
        self.provider = OtherProviderClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model_name,
            timeout=settings.llm_timeout,
        )

    def _parse_provider_response(self, response_data: Dict[str, Any]) -> Any:
        content = (
            response_data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        json_text = _extract_json_text(content if isinstance(content, str) else str(content))
        logger.info("LLM raw content snippet: %s", str(content)[:300].replace("\n", " "))
        return json.loads(json_text)

    def _normalize_items(self, parsed_payload: Any, upload_time: datetime) -> List[ProductItem]:
        raw_items: List[Dict[str, Any]]
        if isinstance(parsed_payload, list):
            raw_items = [x for x in parsed_payload if isinstance(x, dict)]
        elif isinstance(parsed_payload, dict):
            if isinstance(parsed_payload.get("items"), list):
                raw_items = [x for x in parsed_payload["items"] if isinstance(x, dict)]
            else:
                raw_items = [parsed_payload]
        else:
            raise ValueError("Model response is not a JSON object/array.")

        items: List[ProductItem] = []
        for row in raw_items:
            normalized = dict(row)
            normalized["order_created_at"] = upload_time.isoformat()
            items.append(ProductItem.model_validate(normalized))
        return items

    def _normalize_sales_items(self, parsed_payload: Any, upload_time: datetime) -> List[SalesLineItem]:
        raw_items: List[Dict[str, Any]]
        if isinstance(parsed_payload, list):
            raw_items = [x for x in parsed_payload if isinstance(x, dict)]
        elif isinstance(parsed_payload, dict):
            if isinstance(parsed_payload.get("items"), list):
                raw_items = [x for x in parsed_payload["items"] if isinstance(x, dict)]
            else:
                raw_items = [parsed_payload]
        else:
            raise ValueError("Model response is not a JSON object/array.")

        items: List[SalesLineItem] = []
        for row in raw_items:
            normalized = dict(row)
            normalized["order_created_at"] = upload_time.isoformat()
            items.append(SalesLineItem.model_validate(normalized))
        return items

    def parse_product_from_image(self, image_bytes: bytes, upload_time: datetime) -> ParseResult:
        try:
            logger.info(
                "Calling LLM: base_url=%s model=%s image_bytes=%s",
                settings.llm_base_url,
                settings.llm_model_name,
                len(image_bytes),
            )
            raw_response = self.provider.parse_image(image_bytes=image_bytes, prompt=PROMPT_TEMPLATE.strip())
            parsed_payload = self._parse_provider_response(raw_response)
            items = self._normalize_items(parsed_payload, upload_time)
            item = items[0] if items else None
            logger.info(
                "LLM parsed items: count=%s first_product=%s first_total_quantity=%s%s",
                len(items),
                item.product_name if item else "",
                item.total_quantity if item else "",
                item.quantity_unit if item else "",
            )
            return ParseResult(success=True, item=item, items=items)
        except Exception as exc:
            logger.exception("LLM parse failed: %s", exc)
            return ParseResult(success=False, error=str(exc))

    def parse_sales_from_image(self, image_bytes: bytes, upload_time: datetime) -> tuple[bool, list[SalesLineItem], str]:
        try:
            logger.info(
                "Calling LLM (sales): base_url=%s model=%s image_bytes=%s",
                settings.llm_base_url,
                settings.llm_model_name,
                len(image_bytes),
            )
            raw_response = self.provider.parse_image(image_bytes=image_bytes, prompt=SALES_PROMPT_TEMPLATE.strip())
            parsed_payload = self._parse_provider_response(raw_response)
            items = self._normalize_sales_items(parsed_payload, upload_time)
            logger.info("LLM parsed sales items: count=%s", len(items))
            return True, items, ""
        except Exception as exc:
            logger.exception("LLM sales parse failed: %s", exc)
            return False, [], str(exc)

    def classify_material_types(self, names: List[str]) -> dict[str, str]:
        if not names:
            return {}
        user_prompt = build_llm_material_classification_user_prompt(names)
        raw_response = self.provider.chat_text(
            system_prompt=MATERIAL_CLASSIFICATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        parsed_payload = self._parse_provider_response(raw_response)
        if not isinstance(parsed_payload, list):
            return {}

        result: dict[str, str] = {}
        for row in parsed_payload:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            cn_type = str(row.get("type", "")).strip()
            if not name:
                continue
            if cn_type == "即时消耗":
                result[name.lower()] = "instant"
            elif cn_type == "非即时消耗":
                result[name.lower()] = "non_instant"
        return result
