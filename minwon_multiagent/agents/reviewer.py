"""4단계: 검수_Agent — 말투/정확성/근거 점검 및 수정안 제시."""
from __future__ import annotations

from core.models import Draft, Review, SearchResult
from core.openrouter import OpenRouterClient

from ._shared import extract_json

SYSTEM_PROMPT = """당신은 공공기관 민원 답변 품질 검수관입니다.
작성_Agent의 답변 초안을 아래 3가지 관점으로 점검합니다.

1. 말투(tone): 공문체·존댓말·정중함이 적절한가
2. 정확성(accuracy): 사실/수치/조문 인용에 오류가 없는가
3. 근거(evidence): 모든 핵심 주장에 근거가 제시되었는가

점검 후, 문제를 반영해 개선한 '최종 수정 초안'도 함께 제시합니다.
반드시 아래 형식의 JSON 한 개만 출력하세요.

{
  "tone_check": "말투 점검 결과",
  "accuracy_check": "정확성 점검 결과",
  "evidence_check": "근거 점검 결과",
  "overall": "종합 의견(통과/보완필요 등)",
  "revised_draft": "검수를 반영한 최종 수정 초안 전문"
}"""


def review(
    client: OpenRouterClient,
    draft: Draft,
    search_result: SearchResult,
    model: str,
) -> Review:
    """초안의 말투·정확성·근거를 점검하고 수정안을 만든다."""
    user_prompt = _build_prompt(draft, search_result)
    response = client.chat(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.2,
    )
    parsed = extract_json(response.content)
    return Review(
        tone_check=parsed.get("tone_check") or "점검 결과 파싱 실패",
        accuracy_check=parsed.get("accuracy_check") or "점검 결과 파싱 실패",
        evidence_check=parsed.get("evidence_check") or "점검 결과 파싱 실패",
        overall=parsed.get("overall") or response.content[:300],
        revised_draft=parsed.get("revised_draft") or draft.content,
    )


def _build_prompt(draft: Draft, search_result: SearchResult) -> str:
    return (
        "[검색_Agent가 제공한 근거]\n"
        f"{search_result.handoff_text()}\n\n"
        "[작성_Agent의 답변 초안]\n"
        f"{draft.content}\n\n"
        "위 초안을 말투·정확성·근거 관점으로 점검하세요."
    )
