"""단계 간 핸드오프(handoff) 페이로드를 표현하는 불변 데이터 구조.

각 dataclass는 frozen=True 로 불변성을 보장한다 (생성만, 변경 없음).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Minwon:
    """입력 민원 원문."""

    number: str
    title: str
    body: str

    @property
    def full_text(self) -> str:
        return f"[제목] {self.title}\n\n[본문]\n{self.body}".strip()


@dataclass(frozen=True)
class Citation:
    """검색_Agent가 수집한 웹 출처."""

    title: str
    url: str


@dataclass(frozen=True)
class Classification:
    """1단계 산출물 → 2단계로 전달.

    핸드오프: 민원 원문 + 판별된 부서 + 판별된 유형
    """

    minwon: Minwon
    department: str
    complaint_type: str
    rationale: str

    def handoff_text(self) -> str:
        return (
            f"■ 판별된 부서: {self.department}\n"
            f"■ 판별된 유형: {self.complaint_type}\n"
            f"■ 판별 근거: {self.rationale}\n\n"
            f"■ 민원 원문\n{self.minwon.full_text}"
        )


@dataclass(frozen=True)
class SearchResult:
    """2단계 산출물 → 3단계로 전달.

    핸드오프: 법령근거 + 과거 답변 요약
    """

    legal_basis: str
    past_answers: str
    citations: tuple[Citation, ...] = field(default_factory=tuple)

    def handoff_text(self) -> str:
        cites = "\n".join(f"- {c.title}: {c.url}" for c in self.citations)
        return (
            f"■ 관련 법령근거\n{self.legal_basis}\n\n"
            f"■ 관련 과거 답변 요약\n{self.past_answers}\n\n"
            f"■ 출처\n{cites or '(출처 없음)'}"
        )


@dataclass(frozen=True)
class Draft:
    """3단계 산출물 → 4단계로 전달.

    핸드오프: 근거 인용을 포함한 답변 초안
    """

    content: str


@dataclass(frozen=True)
class Review:
    """4단계 산출물: 검수 결과."""

    tone_check: str
    accuracy_check: str
    evidence_check: str
    overall: str
    revised_draft: str
