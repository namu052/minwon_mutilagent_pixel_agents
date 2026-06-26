"""에이전트 공통 유틸: JSON 추출 등."""
from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict:
    """LLM 출력에서 첫 번째 JSON 객체를 추출해 dict로 반환한다.

    ```json ... ``` 코드펜스 또는 본문 내 중괄호 블록을 모두 처리한다.
    실패 시 빈 dict를 반환한다(호출부에서 폴백 처리).
    """
    if not text:
        return {}

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else _first_brace_block(text)
    if not candidate:
        return {}

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _first_brace_block(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""
