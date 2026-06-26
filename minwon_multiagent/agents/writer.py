"""3단계: 작성_Agent — 근거 기반 답변 초안 작성.

핸드오프(→4단계): 근거 인용을 포함한 답변 초안
"""
from __future__ import annotations

from core.models import Classification, Draft, SearchResult
from core.openrouter import OpenRouterClient

SYSTEM_PROMPT = """당신은 공공기관 민원 답변서 작성 담당자입니다.
검색_Agent가 제공한 법령근거와 과거 답변만을 근거로,
민원인에게 보낼 공식 답변 초안을 작성합니다.

작성 원칙:
- 정중하고 명확한 공문 말투(존댓말)를 사용합니다.
- 주장에는 반드시 관련 법령/조문 또는 출처를 본문에 인용합니다.
- 근거가 부족한 부분은 단정하지 말고 '확인이 필요하다'고 안내합니다.
- 구조: ① 인사·문의요지 확인 ② 관련 근거 ③ 답변 ④ 안내·맺음말

순수한 답변 초안 본문만 출력하세요(메타 설명 금지)."""


def write(
    client: OpenRouterClient,
    classification: Classification,
    search_result: SearchResult,
    model: str,
) -> Draft:
    """법령근거·과거 답변을 바탕으로 답변 초안을 작성한다."""
    user_prompt = _build_prompt(classification, search_result)
    response = client.chat(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.4,
    )
    return Draft(content=response.content or "(초안 생성 실패)")


def _build_prompt(
    classification: Classification, search_result: SearchResult
) -> str:
    return (
        "[민원 분류]\n"
        f"- 부서: {classification.department}\n"
        f"- 유형: {classification.complaint_type}\n\n"
        f"[민원 원문]\n{classification.minwon.full_text}\n\n"
        f"[검색_Agent 핸드오프]\n{search_result.handoff_text()}\n\n"
        "위 근거를 인용하여 답변 초안을 작성하세요."
    )
