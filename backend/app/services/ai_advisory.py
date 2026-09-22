from __future__ import annotations

import json
import time
from functools import lru_cache

import httpx
from pydantic import ValidationError

from ..config import Settings
from ..domain.catalog import LEAF_IDS
from ..schemas import AIAdvicePayload


class AIAdviceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AIAdvisoryClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.failure_count = 0
        self.open_until = 0.0

    def advise(self, project: dict, allowed_items: list[dict], photos: list[dict]) -> AIAdvicePayload:
        if not self.settings.llm_base_url or not self.settings.llm_api_key or not self.settings.llm_model:
            raise AIAdviceError("AI_UNAVAILABLE", "LLM 尚未配置")
        if time.monotonic() < self.open_until:
            raise AIAdviceError("AI_UNAVAILABLE", "LLM 熔断器暂时开启")
        prompt = {
            "project": project,
            "allowed_test_items": allowed_items,
            "photos": photos,
            "output_contract": {
                "recommended_test_items": "array of {test_item_id:string, confidence:number 0..1, reason:string}",
                "warnings": "array of {code:string, message:string, related_test_item_ids:string[]}",
                "photo_suggestions": "array of {test_item_id:string, message:string}",
            },
            "output_example": {
                "recommended_test_items": [
                    {
                        "test_item_id": "visual_inspection",
                        "confidence": 0.8,
                        "reason": "项目包含户外柜体，需要外观检查。",
                    }
                ],
                "warnings": [
                    {
                        "code": "POSSIBLE_MISSING_TEST",
                        "message": "建议确认相关测试是否需要。",
                        "related_test_item_ids": ["visual_inspection"],
                    }
                ],
                "photo_suggestions": [
                    {
                        "test_item_id": "visual_inspection",
                        "message": "建议补充柜体正面照片。",
                    }
                ],
            },
            "rules": [
                "Only use test_item_id from allowed_test_items.",
                "Recommendations are advisory and must never invent ids.",
                "Return JSON only and match output_contract exactly.",
                "Every recommendation, warning, and photo suggestion must be an object, not a string.",
                "Return at most 10 highest-value recommendations, 5 warnings, and 10 photo suggestions.",
            ],
        }
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(
                        self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                        json={
                            "model": self.settings.llm_model,
                            "temperature": 0.1,
                            "response_format": {"type": "json_object"},
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "You are an advisory service for test SOP selection. Follow the provided JSON schema exactly; never return arrays of plain strings.",
                                },
                                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                            ],
                        },
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    result = AIAdvicePayload.model_validate_json(content)
                    referenced = {
                        item.test_item_id for item in result.recommended_test_items
                    } | {item.test_item_id for item in result.photo_suggestions}
                    referenced |= {item_id for warning in result.warnings for item_id in warning.related_test_item_ids}
                    invalid = referenced - LEAF_IDS
                    if invalid:
                        raise AIAdviceError("AI_RESPONSE_INVALID", f"LLM 返回未知测试项：{sorted(invalid)}")
                    self.failure_count = 0
                    return result
            except (httpx.HTTPError, KeyError, TypeError, ValidationError, AIAdviceError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
        self.failure_count += 1
        if self.failure_count >= 5:
            self.open_until = time.monotonic() + 60
        raise AIAdviceError("AI_RESPONSE_INVALID", str(last_error or "LLM 请求失败"))


@lru_cache(maxsize=1)
def get_ai_client() -> AIAdvisoryClient:
    from ..config import get_settings

    return AIAdvisoryClient(get_settings())
