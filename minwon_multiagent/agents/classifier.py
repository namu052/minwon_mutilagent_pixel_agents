"""1단계: 분류_Agent — 부서/유형 판별.

핸드오프(→2단계): 민원 원문 + 판별된 부서 + 판별된 유형
"""
from __future__ import annotations

from core.config import COMPLAINT_TYPE_HINTS, DEPARTMENT_HINTS
from core.models import Classification, Minwon
from core.openrouter import OpenRouterClient

from ._shared import extract_json

SYSTEM_PROMPT = """당신은 대한민국 공공기관의 민원 분류 전문가입니다.
주어진 민원의 '담당 부서'와 '민원 유형'을 판별합니다.
반드시 아래 형식의 JSON 한 개만 출력하세요. 그 외 설명은 금지합니다.

{
  "department": "담당 부서명",
  "complaint_type": "민원 유형",
  "rationale": "판별 근거를 2~3문장으로"
}"""


def classify(client: OpenRouterClient, minwon: Minwon, model: str) -> Classification:
    """민원을 부서/유형으로 분류한다."""
    user_prompt = _build_prompt(minwon)
    response = client.chat(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
    )
    parsed = extract_json(response.content)
    return Classification(
        minwon=minwon,
        department=parsed.get("department") or "판별불가",
        complaint_type=parsed.get("complaint_type") or "판별불가",
        rationale=parsed.get("rationale") or response.content[:300] or "근거 없음",
    )


def _build_prompt(minwon: Minwon) -> str:
    departments = ", ".join(DEPARTMENT_HINTS)
    types = ", ".join(COMPLAINT_TYPE_HINTS)
    return (
        f"[참고 부서 후보] {departments}\n"
        f"[참고 유형 후보] {types}\n"
        "후보에 없으면 가장 적합한 명칭을 직접 판단해도 됩니다.\n\n"
        f"[민원]\n{minwon.full_text}"
    )
