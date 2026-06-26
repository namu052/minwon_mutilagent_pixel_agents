"""2단계: 검색_Agent — 관련 법령 + 과거 답변을 웹검색으로 수집.

핸드오프(→3단계): 법령근거 + 과거 답변 요약
"""
from __future__ import annotations

from core.models import Classification, SearchResult
from core.openrouter import OpenRouterClient

from ._shared import extract_json

SYSTEM_PROMPT = """당신은 대한민국 법령·행정해석 리서처입니다.
제공된 민원에 대해 웹검색을 적극 활용하여
(1) 관련 법령·규정 근거와 (2) 유사한 과거 답변/행정해석 사례를 찾습니다.

반드시 아래 형식의 JSON 한 개만 출력하세요.

{
  "legal_basis": "관련 법령/조문/규정을 근거와 함께 정리 (조문 번호 포함)",
  "past_answers": "유사 민원에 대한 과거 답변·행정해석의 핵심 요약"
}

추측이 아니라 검색으로 확인된 사실 위주로 작성하고,
불확실하면 불확실하다고 명시하세요."""


def search(
    client: OpenRouterClient,
    classification: Classification,
    model: str,
    *,
    web_search: bool = True,
) -> SearchResult:
    """법령근거와 과거 답변을 웹검색 기반으로 수집한다."""
    user_prompt = _build_prompt(classification)
    response = client.chat(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.2,
        web_search=web_search,
    )
    parsed = extract_json(response.content)
    return SearchResult(
        legal_basis=parsed.get("legal_basis") or response.content or "검색 결과 없음",
        past_answers=parsed.get("past_answers") or "유사 사례를 찾지 못했습니다.",
        citations=response.citations,
    )


def _build_prompt(classification: Classification) -> str:
    return (
        "아래 민원에 대한 법령근거와 과거 답변을 웹검색으로 조사하세요.\n\n"
        f"{classification.handoff_text()}"
    )
