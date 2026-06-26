"""민원 초안 생성 Multi-Agent — Streamlit UI.

4단계 파이프라인(분류 → 검색 → 작성 → 검수)을 실행하며
각 단계의 입력/출력/핸드오프를 실시간으로 화면에 표시한다.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from agents import classify, review, search, write
from core.config import DEFAULT_MODELS
from core.models import Citation, Minwon
from core.openrouter import OpenRouterClient, OpenRouterError
from data.loader import load_minwons

BUNDLED_XLSX = Path(__file__).resolve().parent.parent / "1782341096215_file.xlsx"

st.set_page_config(page_title="민원 초안 생성 Multi-Agent", page_icon="📮", layout="wide")


# ----------------------------- 사이드바 설정 ----------------------------- #
def render_sidebar() -> dict:
    """API 키·모델·옵션 입력 사이드바. 설정 dict를 반환한다."""
    st.sidebar.header("⚙️ 설정")
    api_key = st.sidebar.text_input(
        "OpenRouter API Key",
        type="password",
        placeholder="sk-or-...",
        help="https://openrouter.ai/keys 에서 발급",
    )

    st.sidebar.markdown("**단계별 모델** (필요 시 수정)")
    models = {
        "classifier": st.sidebar.text_input("1단계 분류", DEFAULT_MODELS["classifier"]),
        "searcher": st.sidebar.text_input("2단계 검색", DEFAULT_MODELS["searcher"]),
        "writer": st.sidebar.text_input("3단계 작성", DEFAULT_MODELS["writer"]),
        "reviewer": st.sidebar.text_input("4단계 검수", DEFAULT_MODELS["reviewer"]),
    }
    web_search = st.sidebar.checkbox(
        "검색_Agent 웹검색 사용", value=True,
        help="OpenRouter web 플러그인으로 실시간 검색",
    )
    return {"api_key": api_key, "models": models, "web_search": web_search}


# ----------------------------- 민원 선택 ----------------------------- #
def select_minwon() -> Minwon | None:
    """샘플 엑셀 또는 직접 입력으로 민원을 고른다."""
    tab_sample, tab_manual = st.tabs(["📄 샘플 민원 선택", "✍️ 직접 입력"])

    with tab_sample:
        minwon = _select_from_xlsx()
    with tab_manual:
        manual = _manual_input()

    return manual or minwon


def _select_from_xlsx() -> Minwon | None:
    if not BUNDLED_XLSX.exists():
        st.info("샘플 엑셀이 없습니다. '직접 입력' 탭을 사용하세요.")
        return None
    try:
        minwons = load_minwons(BUNDLED_XLSX)
    except (FileNotFoundError, ValueError) as exc:
        st.error(f"엑셀 로드 실패: {exc}")
        return None

    if not minwons:
        st.warning("엑셀에 민원이 없습니다.")
        return None

    labels = [f"{m.number} | {m.title}" for m in minwons]
    idx = st.selectbox(
        "민원 선택", range(len(minwons)),
        format_func=lambda i: labels[i],
    )
    chosen = minwons[idx]
    st.text_area("선택한 민원 본문", chosen.body, height=180, disabled=True)
    return chosen


def _manual_input() -> Minwon | None:
    title = st.text_input("제목", key="manual_title")
    body = st.text_area("본문", height=180, key="manual_body")
    if title.strip() or body.strip():
        return Minwon(number="DIRECT-INPUT", title=title.strip(), body=body.strip())
    return None


# ----------------------------- 파이프라인 실행 ----------------------------- #
def run_pipeline(client: OpenRouterClient, minwon: Minwon, cfg: dict) -> None:
    """4단계를 순차 실행하며 각 단계를 화면에 렌더링한다."""
    progress = st.progress(0, text="파이프라인 시작...")

    classification = _run_classify(client, minwon, cfg, progress)
    if classification is None:
        return
    result = _run_search(client, classification, cfg, progress)
    if result is None:
        return
    draft = _run_write(client, classification, result, cfg, progress)
    if draft is None:
        return
    reviewed = _run_review(client, draft, result, cfg, progress)
    if reviewed is None:
        return

    progress.progress(100, text="완료 ✓")
    _render_final(reviewed)


def _run_classify(client, minwon, cfg, progress):
    with st.status("🟦 1단계 · 분류_Agent — 부서/유형 판별 중...", expanded=True) as s:
        try:
            classification = classify(client, minwon, cfg["models"]["classifier"])
        except OpenRouterError as exc:
            s.update(label="1단계 실패 ❌", state="error")
            st.error(str(exc))
            return None
        col1, col2 = st.columns(2)
        col1.metric("판별 부서", classification.department)
        col2.metric("민원 유형", classification.complaint_type)
        st.caption(f"판별 근거: {classification.rationale}")
        _handoff_box("1단계 → 2단계 핸드오프", classification.handoff_text())
        s.update(label="🟦 1단계 · 분류 완료 ✓", state="complete")
    progress.progress(25, text="분류 완료")
    return classification


def _run_search(client, classification, cfg, progress):
    with st.status("🟩 2단계 · 검색_Agent — 법령/과거답변 웹검색 중...", expanded=True) as s:
        try:
            result = search(
                client, classification, cfg["models"]["searcher"],
                web_search=cfg["web_search"],
            )
        except OpenRouterError as exc:
            s.update(label="2단계 실패 ❌", state="error")
            st.error(str(exc))
            return None
        st.markdown("**📚 관련 법령근거**")
        st.write(result.legal_basis)
        st.markdown("**🗂️ 과거 답변 요약**")
        st.write(result.past_answers)
        _render_citations(result.citations)
        _handoff_box("2단계 → 3단계 핸드오프", result.handoff_text())
        s.update(label="🟩 2단계 · 검색 완료 ✓", state="complete")
    progress.progress(50, text="검색 완료")
    return result


def _run_write(client, classification, result, cfg, progress):
    with st.status("🟨 3단계 · 작성_Agent — 근거 기반 초안 작성 중...", expanded=True) as s:
        try:
            draft = write(client, classification, result, cfg["models"]["writer"])
        except OpenRouterError as exc:
            s.update(label="3단계 실패 ❌", state="error")
            st.error(str(exc))
            return None
        st.markdown("**📝 답변 초안**")
        st.write(draft.content)
        _handoff_box("3단계 → 4단계 핸드오프 (근거 인용 포함 초안)", draft.content)
        s.update(label="🟨 3단계 · 작성 완료 ✓", state="complete")
    progress.progress(75, text="작성 완료")
    return draft


def _run_review(client, draft, result, cfg, progress):
    with st.status("🟥 4단계 · 검수_Agent — 말투/정확성/근거 점검 중...", expanded=True) as s:
        try:
            reviewed = review(client, draft, result, cfg["models"]["reviewer"])
        except OpenRouterError as exc:
            s.update(label="4단계 실패 ❌", state="error")
            st.error(str(exc))
            return None
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**🗣️ 말투**\n\n{reviewed.tone_check}")
        c2.markdown(f"**🎯 정확성**\n\n{reviewed.accuracy_check}")
        c3.markdown(f"**🔖 근거**\n\n{reviewed.evidence_check}")
        st.info(f"**종합 의견:** {reviewed.overall}")
        s.update(label="🟥 4단계 · 검수 완료 ✓", state="complete")
    return reviewed


# ----------------------------- 렌더 헬퍼 ----------------------------- #
def _handoff_box(title: str, text: str) -> None:
    with st.expander(f"📦 {title}", expanded=False):
        st.code(text, language="text")


def _render_citations(citations: tuple[Citation, ...]) -> None:
    if not citations:
        st.caption("🔗 출처: (웹검색 출처 없음)")
        return
    st.markdown("**🔗 출처**")
    for c in citations:
        st.markdown(f"- [{c.title}]({c.url})")


def _render_final(reviewed) -> None:
    st.success("✅ 최종 답변 초안이 완성되었습니다.")
    st.markdown("## 📨 최종 답변 초안 (검수 반영)")
    st.write(reviewed.revised_draft)
    st.download_button(
        "⬇️ 초안 다운로드 (.txt)",
        data=reviewed.revised_draft,
        file_name="민원답변초안.txt",
        mime="text/plain",
    )


# ----------------------------- 메인 ----------------------------- #
def main() -> None:
    st.title("📮 민원 초안 생성 Multi-Agent")
    st.caption("분류 → 검색 → 작성 → 검수 4단계 에이전트 파이프라인")

    cfg = render_sidebar()
    minwon = select_minwon()

    st.divider()
    if st.button("🚀 멀티에이전트 실행", type="primary", use_container_width=True):
        if not cfg["api_key"].strip():
            st.error("사이드바에 OpenRouter API 키를 입력하세요.")
            return
        if minwon is None:
            st.error("처리할 민원을 선택하거나 입력하세요.")
            return
        try:
            client = OpenRouterClient(cfg["api_key"])
        except OpenRouterError as exc:
            st.error(str(exc))
            return
        run_pipeline(client, minwon, cfg)


if __name__ == "__main__":
    main()
