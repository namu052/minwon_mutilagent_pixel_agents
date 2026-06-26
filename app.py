from __future__ import annotations

import base64
import importlib
import json
from html import escape as html_escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import complaint_agents as complaint_agents_module


complaint_agents_module = importlib.reload(complaint_agents_module)
ComplaintSupervisor = complaint_agents_module.ComplaintSupervisor
DEFAULT_MODELS = complaint_agents_module.DEFAULT_MODELS
OpenRouterClient = complaint_agents_module.OpenRouterClient
OpenRouterError = complaint_agents_module.OpenRouterError
normalize_text = complaint_agents_module.normalize_text


BASE_DIR = Path(__file__).resolve().parent
SAMPLE_XLSX = BASE_DIR / "1782341096215_file.xlsx"
PIXEL_ASSET_DIR = BASE_DIR / "assets" / "pixel_office"

OFFICE_AGENTS = [
    ("분류_Agent", "classification_agent_tool"),
    ("검색_Agent", "search_agent_tool"),
    ("작성_Agent", "writing_agent_tool"),
    ("검수_Agent", "review_agent_tool"),
]


@st.cache_data(show_spinner=False)
def load_sample_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path).fillna("")
    return df


def sample_label(df: pd.DataFrame, idx: int) -> str:
    row = df.iloc[idx]
    complaint_no = normalize_text(row.iloc[0])
    title = normalize_text(row.iloc[1])
    if len(title) > 54:
        title = title[:54] + "..."
    return f"{complaint_no} | {title}"


def set_sample(df: pd.DataFrame, idx: int) -> None:
    row = df.iloc[idx]
    st.session_state["complaint_title"] = normalize_text(row.iloc[1])
    st.session_state["complaint_body"] = normalize_text(row.iloc[2])
    st.session_state["complaint_no"] = normalize_text(row.iloc[0])


@st.cache_data(show_spinner=False)
def pixel_asset_data_uri(relative_path: str) -> str:
    path = PIXEL_ASSET_DIR / relative_path
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_idle_runtime_snapshot(model_settings: dict[str, str]) -> dict[str, Any]:
    return {
        "session_id": "minwon-ready",
        "agents": [
            {
                "id": index,
                "name": agent_name,
                "role": "민원 처리 Agent",
                "model": model_settings[model_key],
                "status": "waiting",
                "active_tool_id": "",
                "active_tool_name": "",
                "last_message": "대기 중",
                "outputs": [],
            }
            for index, ((agent_name, tool_name), model_key) in enumerate(
                zip(OFFICE_AGENTS, ["classification", "search", "writing", "review"]),
                start=1,
            )
        ],
        "events": [],
    }


def render_pixel_office(snapshot: dict[str, Any]) -> None:
    agents = snapshot.get("agents") or []
    if not agents:
        return

    assets = {
        "floor": pixel_asset_data_uri("floors/floor_1.png"),
        "wall": pixel_asset_data_uri("walls/wall_0.png"),
        "bookshelf": pixel_asset_data_uri("furniture/BOOKSHELF/BOOKSHELF.png"),
        "desk": pixel_asset_data_uri("furniture/DESK/DESK_FRONT.png"),
        "pc_on": pixel_asset_data_uri("furniture/PC/PC_FRONT_ON_1.png"),
        "pc_off": pixel_asset_data_uri("furniture/PC/PC_FRONT_OFF.png"),
        "plant": pixel_asset_data_uri("furniture/LARGE_PLANT/LARGE_PLANT.png"),
        "whiteboard": pixel_asset_data_uri("furniture/WHITEBOARD/WHITEBOARD.png"),
        "clock": pixel_asset_data_uri("furniture/CLOCK/CLOCK.png"),
    }
    characters = [
        pixel_asset_data_uri(f"characters/char_{i}.png")
        for i in range(6)
    ]

    station_lefts = [96, 256, 416, 576]
    tool_order = [tool_name for _, tool_name in OFFICE_AGENTS]
    completed_handoff_indexes: list[int] = []
    for event in snapshot.get("events") or []:
        if event.get("type") != "handoffProduced":
            continue
        tool_name = event.get("toolName")
        if tool_name not in tool_order:
            continue
        handoff_index = tool_order.index(tool_name)
        if handoff_index >= len(station_lefts) - 1:
            continue
        if handoff_index not in completed_handoff_indexes:
            completed_handoff_indexes.append(handoff_index)

    handoff_participants = {
        index
        for handoff_index in completed_handoff_indexes
        for index in (handoff_index, handoff_index + 1)
    }

    agent_html = []
    for idx, agent in enumerate(agents[:4]):
        left = station_lefts[idx]
        status = str(agent.get("status") or "waiting")
        status_class = status if status in {"active", "waiting", "error"} else "waiting"
        label = html_escape(str(agent.get("name") or f"Agent {idx + 1}"))
        message = str(agent.get("last_message") or "대기 중")
        model = html_escape(str(agent.get("model") or ""))
        tool = html_escape(str(agent.get("active_tool_name") or ""))
        agent_name = str(agent.get("name") or "")
        char_uri = characters[idx % len(characters)]
        pc_uri = assets["pc_on"] if status_class == "active" else assets["pc_off"]
        bubble_text = message if len(message) <= 34 else message[:31] + "..."
        bubble_text = html_escape(bubble_text)
        if status_class == "active" and "검색" in agent_name:
            activity_class = "reading"
        elif status_class == "active" and "검수" in agent_name:
            activity_class = "reviewing"
        elif status_class == "active":
            activity_class = "typing"
        elif status_class == "error":
            activity_class = "alert"
        else:
            activity_class = "idle"
        handoff_class = " handoff-ready" if idx in handoff_participants and status_class != "active" else ""
        active_papers = '<div class="work-paper one"></div><div class="work-paper two"></div>' if status_class == "active" else ""
        agent_html.append(
            f"""
            <div class="station station-{status_class}{handoff_class}" style="left:{left}px">
              <div class="speech">{bubble_text}</div>
              <img class="pc" src="{pc_uri}" alt="">
              <img class="desk" src="{assets['desk']}" alt="">
              {active_papers}
              <div class="character {status_class} {activity_class}{handoff_class}" style="background-image:url('{char_uri}')"></div>
              <div class="nameplate">
                <strong>{label}</strong>
                <span>{tool or status_class}</span>
              </div>
              <div class="model">{model}</div>
            </div>
            """
        )

    handoff_html = []
    for order, handoff_index in enumerate(completed_handoff_indexes):
        start_left = station_lefts[handoff_index] + 86
        travel = station_lefts[handoff_index + 1] - station_lefts[handoff_index]
        delay = order * 0.42
        handoff_html.append(
            f"""
            <div class="handoff-lane" style="left:{start_left}px; --travel:{travel}px; animation-delay:{delay}s"></div>
            <div class="handoff-paper" style="left:{start_left}px; --travel:{travel}px; animation-delay:{delay}s">
              <span></span>
            </div>
            """
        )

    office_html = f"""
    <div class="pixel-office">
      <div class="office-stage">
        <div class="wall"></div>
        <div class="floor"></div>
        <img class="prop shelf shelf-left" src="{assets['bookshelf']}" alt="">
        <img class="prop shelf shelf-mid" src="{assets['bookshelf']}" alt="">
        <img class="prop shelf shelf-right" src="{assets['bookshelf']}" alt="">
        <img class="prop plant" src="{assets['plant']}" alt="">
        <img class="prop whiteboard" src="{assets['whiteboard']}" alt="">
        <img class="prop clock" src="{assets['clock']}" alt="">
        {''.join(agent_html)}
        {''.join(handoff_html)}
      </div>
    </div>
    <style>
      * {{
        box-sizing: border-box;
      }}
      body {{
        margin: 0;
        background: transparent;
        font-family: "Segoe UI", sans-serif;
      }}
      .pixel-office {{
        width: 100%;
        padding: 6px 0 10px;
      }}
      .office-stage {{
        position: relative;
        width: 820px;
        max-width: 100%;
        height: 292px;
        margin: 0 auto;
        overflow: hidden;
        border: 4px solid #1b1d35;
        background: #14172b;
        image-rendering: pixelated;
        box-shadow: 0 8px 0 #0e1020;
      }}
      .wall {{
        position: absolute;
        inset: 0 0 auto 0;
        height: 96px;
        background-color: #343854;
        background-image: url("{assets['wall']}");
        background-size: 64px 128px;
        background-repeat: repeat;
        border-bottom: 4px solid #24243a;
      }}
      .floor {{
        position: absolute;
        inset: 96px 0 0 0;
        background-color: #b9874b;
        background-image: url("{assets['floor']}");
        background-size: 32px 32px;
        background-repeat: repeat;
      }}
      .prop {{
        position: absolute;
        image-rendering: pixelated;
      }}
      .shelf {{
        top: 28px;
        width: 80px;
      }}
      .shelf-left {{ left: 26px; }}
      .shelf-mid {{ left: 170px; }}
      .shelf-right {{ right: 46px; }}
      .plant {{
        left: 28px;
        top: 120px;
        width: 38px;
      }}
      .whiteboard {{
        right: 154px;
        top: 38px;
        width: 72px;
      }}
      .clock {{
        right: 254px;
        top: 18px;
        width: 22px;
      }}
      .station {{
        position: absolute;
        top: 0;
        width: 116px;
        height: 292px;
      }}
      .desk {{
        position: absolute;
        left: 18px;
        top: 132px;
        width: 96px;
        image-rendering: pixelated;
        z-index: 5;
      }}
      .pc {{
        position: absolute;
        left: 56px;
        top: 104px;
        width: 32px;
        image-rendering: pixelated;
        z-index: 6;
      }}
      .character {{
        position: absolute;
        left: 47px;
        top: 181px;
        width: 16px;
        height: 32px;
        background-repeat: no-repeat;
        background-size: 112px 96px;
        background-position: 0 0;
        image-rendering: pixelated;
        transform: scale(2);
        transform-origin: top left;
        z-index: 9;
      }}
      .character.idle {{
        animation: idle-wander 4.4s steps(4) infinite;
      }}
      .character.typing {{
        animation: typing 0.55s steps(1) infinite;
      }}
      .character.reading {{
        animation: reading 0.72s steps(1) infinite;
      }}
      .character.reviewing {{
        animation: review-walk 1.2s steps(3) infinite;
      }}
      .character.alert {{
        animation: alert-shake .32s steps(2) infinite;
        filter: hue-rotate(145deg) saturate(1.7);
      }}
      .character.handoff-ready {{
        animation: handoff-ready 1.15s steps(2) infinite;
      }}
      .work-paper {{
        position: absolute;
        top: 151px;
        width: 18px;
        height: 13px;
        background: #fff7d6;
        border: 2px solid #252747;
        z-index: 8;
        animation: work-paper-float 1.1s steps(3) infinite;
      }}
      .work-paper.one {{
        left: 36px;
      }}
      .work-paper.two {{
        left: 66px;
        animation-delay: .25s;
      }}
      .work-paper::before {{
        content: "";
        position: absolute;
        left: 3px;
        top: 3px;
        width: 8px;
        height: 2px;
        background: #6a6f91;
        box-shadow: 0 4px 0 #6a6f91;
      }}
      @keyframes idle-wander {{
        0%, 100% {{ background-position: 0 0; transform: translate(0, 0) scale(2); }}
        25% {{ background-position: -16px 0; transform: translate(-2px, 0) scale(2); }}
        50% {{ background-position: -32px 0; transform: translate(2px, 0) scale(2); }}
        75% {{ background-position: -16px 0; transform: translate(0, 1px) scale(2); }}
      }}
      @keyframes typing {{
        0% {{ background-position: -48px 0; transform: translate(0, 0) scale(2); }}
        50% {{ background-position: -64px 0; transform: translate(0, -1px) scale(2); }}
        100% {{ background-position: -48px 0; transform: translate(0, 0) scale(2); }}
      }}
      @keyframes reading {{
        0% {{ background-position: -80px 0; transform: translate(-4px, -2px) scale(2); }}
        50% {{ background-position: -96px 0; transform: translate(-2px, -2px) scale(2); }}
        100% {{ background-position: -80px 0; transform: translate(-4px, -2px) scale(2); }}
      }}
      @keyframes review-walk {{
        0% {{ background-position: 0 -64px; transform: translate(-6px, -18px) scale(2); }}
        33% {{ background-position: -16px -64px; transform: translate(2px, -20px) scale(2); }}
        66% {{ background-position: -32px -64px; transform: translate(9px, -18px) scale(2); }}
        100% {{ background-position: 0 -64px; transform: translate(-6px, -18px) scale(2); }}
      }}
      @keyframes handoff-ready {{
        0% {{ background-position: 0 -64px; transform: translate(0, 0) scale(2); }}
        50% {{ background-position: -16px -64px; transform: translate(6px, -1px) scale(2); }}
        100% {{ background-position: 0 -64px; transform: translate(0, 0) scale(2); }}
      }}
      @keyframes alert-shake {{
        0%, 100% {{ background-position: 0 0; transform: translate(-2px, 0) scale(2); }}
        50% {{ background-position: -16px 0; transform: translate(2px, 0) scale(2); }}
      }}
      @keyframes work-paper-float {{
        0%, 100% {{ transform: translateY(0); }}
        50% {{ transform: translateY(-5px); }}
      }}
      .handoff-lane {{
        position: absolute;
        top: 212px;
        width: var(--travel);
        height: 2px;
        border-top: 2px dotted rgba(37, 39, 71, .7);
        z-index: 11;
        animation: lane-pulse 2.4s steps(3) infinite;
      }}
      .handoff-paper {{
        position: absolute;
        top: 198px;
        width: 22px;
        height: 18px;
        background: #fff7d6;
        border: 3px solid #252747;
        box-shadow: 3px 3px 0 rgba(0, 0, 0, .25);
        z-index: 30;
        animation: pass-paper 2.4s steps(12) infinite;
      }}
      .handoff-paper::before {{
        content: "";
        position: absolute;
        left: 3px;
        top: 4px;
        width: 11px;
        height: 2px;
        background: #6a6f91;
        box-shadow: 0 5px 0 #6a6f91;
      }}
      .handoff-paper::after {{
        content: "";
        position: absolute;
        right: -8px;
        top: 4px;
        width: 0;
        height: 0;
        border-top: 4px solid transparent;
        border-bottom: 4px solid transparent;
        border-left: 7px solid #252747;
      }}
      .handoff-paper span {{
        position: absolute;
        left: -9px;
        top: 16px;
        width: 8px;
        height: 8px;
        background: #f4c14e;
        border: 2px solid #252747;
      }}
      @keyframes pass-paper {{
        0% {{
          transform: translate(0, 0) rotate(0deg);
          opacity: 0;
        }}
        8% {{
          opacity: 1;
        }}
        40% {{
          transform: translate(calc(var(--travel) * .52), -18px) rotate(-5deg);
          opacity: 1;
        }}
        82% {{
          transform: translate(calc(var(--travel) - 18px), 0) rotate(3deg);
          opacity: 1;
        }}
        100% {{
          transform: translate(calc(var(--travel) - 18px), 0) rotate(3deg);
          opacity: 0;
        }}
      }}
      @keyframes lane-pulse {{
        0%, 100% {{ opacity: .18; }}
        50% {{ opacity: .78; }}
      }}
      .speech {{
        position: absolute;
        left: -4px;
        top: 72px;
        width: 124px;
        min-height: 34px;
        padding: 5px 7px;
        color: #20223a;
        background: #fff6c8;
        border: 3px solid #252747;
        font-size: 11px;
        line-height: 1.25;
        z-index: 20;
        box-shadow: 3px 3px 0 rgba(0,0,0,.22);
      }}
      .speech::after {{
        content: "";
        position: absolute;
        left: 48px;
        bottom: -9px;
        width: 10px;
        height: 10px;
        background: #fff6c8;
        border-right: 3px solid #252747;
        border-bottom: 3px solid #252747;
        transform: rotate(45deg);
      }}
      .station-active .speech {{
        background: #d8f8ff;
      }}
      .station-active .speech::after {{
        background: #d8f8ff;
      }}
      .station-error .speech {{
        background: #ffd8d8;
      }}
      .station-error .speech::after {{
        background: #ffd8d8;
      }}
      .nameplate {{
        position: absolute;
        left: 0;
        top: 251px;
        width: 126px;
        padding: 3px 5px;
        color: #f6f6ff;
        background: rgba(19, 20, 38, .88);
        border: 2px solid #3f456d;
        font-size: 11px;
        line-height: 1.15;
        z-index: 15;
      }}
      .nameplate strong,
      .nameplate span,
      .model {{
        display: block;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }}
      .nameplate span {{
        color: #b6c4ff;
        font-size: 10px;
      }}
      .model {{
        position: absolute;
        left: 0;
        top: 274px;
        width: 126px;
        color: #d6d9ff;
        font-size: 9px;
        z-index: 16;
        opacity: .82;
      }}
    </style>
    """
    components.html(office_html, height=322, scrolling=False)


def render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        st.caption("검색 결과 없음")
        return

    for source in sources:
        title = normalize_text(source.get("title")) or "제목 없음"
        url = normalize_text(source.get("url"))
        query = normalize_text(source.get("query"))
        snippet = normalize_text(source.get("snippet"))
        if url:
            st.markdown(f"- [{title}]({url})")
        else:
            st.markdown(f"- {title}")
        if query:
            st.caption(f"검색어: {query}")
        if snippet:
            st.caption(snippet)


def render_pixel_runtime(snapshot: dict[str, Any]) -> None:
    st.markdown("#### Pixel-Agent Runtime")
    st.caption(
        "pixel-agents의 AgentStateStore/broadcast 흐름을 민원 Supervisor 실행 상태로 변환한 화면입니다."
    )
    st.code(snapshot.get("session_id", ""), language="text")
    render_pixel_office(snapshot)

    agents = snapshot.get("agents") or []
    if agents:
        cols = st.columns(len(agents))
        for col, agent in zip(cols, agents):
            with col:
                status = agent.get("status", "waiting")
                icon = {"active": "🟢", "waiting": "⚪", "error": "🔴"}.get(status, "⚪")
                st.markdown(f"**{icon} {agent.get('name', 'Agent')}**")
                st.caption(agent.get("model", ""))
                st.write(agent.get("last_message", ""))
                active_tool = agent.get("active_tool_name")
                if active_tool:
                    st.code(active_tool, language="text")
                outputs = agent.get("outputs") or []
                if outputs:
                    st.caption("출력: " + ", ".join(outputs))

    events = snapshot.get("events") or []
    if not events:
        return

    rows = [
        {
            "seq": event.get("seq"),
            "time": event.get("time"),
            "type": event.get("type"),
            "agent_id": event.get("id", ""),
            "tool": event.get("toolName", ""),
            "status": event.get("status", ""),
            "label": event.get("label", ""),
        }
        for event in events[-16:]
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_results(result: dict[str, Any]) -> None:
    st.subheader("Supervisor(as tool) 검수 완료 답변")
    st.markdown(result["review"]["final_answer"])

    st.download_button(
        "결과 JSON 다운로드",
        data=json.dumps(result, ensure_ascii=False, indent=2),
        file_name="complaint_multi_agent_result.json",
        mime="application/json",
        width="stretch",
    )

    tabs = st.tabs(
        [
            "Supervisor",
            "Pixel Runtime",
            "1단계 분류",
            "2단계 검색",
            "3단계 작성",
            "4단계 검수",
            "웹검색 출처",
        ]
    )

    with tabs[0]:
        st.markdown("#### Supervisor(as tool) 실행 구조")
        st.json(
            {
                "architecture": result.get("architecture"),
                "policy": result["supervisor"]["policy"],
                "tool_registry": result["supervisor"]["tool_registry"],
                "trace": result["supervisor"]["trace"],
            },
            expanded=True,
        )

    with tabs[1]:
        runtime_snapshot = result.get("pixel_runtime")
        if runtime_snapshot:
            render_pixel_runtime(runtime_snapshot)
        else:
            st.info("Pixel runtime 기록이 없습니다. 새로 실행하면 표시됩니다.")

    with tabs[2]:
        st.markdown("#### 분류_Agent 결과")
        st.json(result["classification"], expanded=False)
        st.markdown("#### 1단계 -> 2단계 핸드오프")
        st.json(result["handoffs"]["classification_to_search"], expanded=True)

    with tabs[3]:
        st.markdown("#### 검색_Agent 결과")
        st.json(
            {
                "search_queries": result["search"]["search_queries"],
                "law_basis": result["search"]["law_basis"],
                "past_answer_summaries": result["search"]["past_answer_summaries"],
                "limitations": result["search"]["limitations"],
            },
            expanded=True,
        )
        st.markdown("#### 2단계 -> 3단계 핸드오프")
        st.json(result["handoffs"]["search_to_writing"], expanded=True)

    with tabs[4]:
        st.markdown("#### 작성_Agent 초안")
        st.markdown(result["draft"]["draft"])
        st.markdown("#### 3단계 -> 4단계 핸드오프")
        st.json(result["handoffs"]["writing_to_review"], expanded=True)

    with tabs[5]:
        st.markdown("#### 검수_Agent 결과")
        st.json(result["review"], expanded=True)

    with tabs[6]:
        left, right = st.columns(2)
        with left:
            st.markdown("#### 법령 검색")
            render_sources(result["search"]["sources"]["law_sources"])
        with right:
            st.markdown("#### 과거 답변 검색")
            render_sources(result["search"]["sources"]["past_answer_sources"])


def run_pipeline(
    *,
    api_key: str,
    title: str,
    body: str,
    model_settings: dict[str, str],
    max_results: int,
    read_pages: bool,
) -> dict[str, Any] | None:
    client = OpenRouterClient(api_key)
    supervisor = ComplaintSupervisor(
        client,
        model_settings=model_settings,
        max_results_per_category=max_results,
        read_pages=read_pages,
    )
    state = supervisor.initial_state(title=title, body=body)

    progress = st.progress(0)
    runtime_slot = st.empty()

    def render_runtime_snapshot(snapshot: dict[str, Any]) -> None:
        with runtime_slot.container():
            render_pixel_runtime(snapshot)

    render_runtime_snapshot(supervisor.runtime.to_snapshot())
    total_tools = len(supervisor.tools)

    try:
        for index, tool in enumerate(supervisor.tools, start=1):
            with st.status(
                f"Supervisor 도구 호출 {index}/{total_tools}: {tool.agent}",
                expanded=True,
            ) as status:
                st.write(f"도구 이름: `{tool.name}`")
                st.write(tool.description)
                st.caption(f"입력 상태: {', '.join(tool.requires)}")
                st.caption(f"출력 상태: {', '.join(tool.provides)}")

                event = supervisor.invoke_tool(
                    tool.name,
                    state,
                    on_runtime_event=render_runtime_snapshot,
                )

                st.write(event["display_label"])
                if isinstance(event["display_payload"], str):
                    st.markdown(event["display_payload"])
                else:
                    st.json(event["display_payload"], expanded=True)

                status.update(
                    label=f"Supervisor 도구 완료 {index}/{total_tools}: {tool.agent}",
                    state="complete",
                )
            progress.progress(int(index / total_tools * 100))

    except OpenRouterError as exc:
        render_runtime_snapshot(supervisor.runtime.to_snapshot())
        st.error(str(exc))
        return None
    except Exception as exc:  # noqa: BLE001
        render_runtime_snapshot(supervisor.runtime.to_snapshot())
        st.error(f"실행 중 오류가 발생했습니다: {exc}")
        return None

    return supervisor.to_result(state)


def main() -> None:
    st.set_page_config(
        page_title="민원 초안 생성 Supervisor(as tool)",
        page_icon="M",
        layout="wide",
    )

    st.title("민원 초안 생성 Supervisor(as tool)")

    if not SAMPLE_XLSX.exists():
        st.error(f"샘플 엑셀 파일을 찾을 수 없습니다: {SAMPLE_XLSX}")
        return

    df = load_sample_data(str(SAMPLE_XLSX))
    if "complaint_title" not in st.session_state:
        set_sample(df, 0)

    with st.sidebar:
        st.header("설정")
        api_key = st.text_input("OpenRouter API Key", type="password")
        max_results = st.slider("검색 결과 수", min_value=2, max_value=8, value=5, step=1)
        read_pages = st.checkbox("검색 결과 본문 일부 읽기", value=True)

        with st.expander("Agent 도구 모델", expanded=False):
            model_settings = {
                "classification": st.text_input(
                    "분류_Agent",
                    value=DEFAULT_MODELS["classification"],
                ),
                "search": st.text_input(
                    "검색_Agent",
                    value=DEFAULT_MODELS["search"],
                ),
                "writing": st.text_input(
                    "작성_Agent",
                    value=DEFAULT_MODELS["writing"],
                ),
                "review": st.text_input(
                    "검수_Agent",
                    value=DEFAULT_MODELS["review"],
                ),
            }

    st.markdown("### Pixel Agents Office")
    preview_snapshot = (
        st.session_state.get("last_result", {}).get("pixel_runtime")
        if isinstance(st.session_state.get("last_result"), dict)
        else None
    )
    render_pixel_office(preview_snapshot or build_idle_runtime_snapshot(model_settings))

    left, right = st.columns([0.34, 0.66], gap="large")

    with left:
        st.subheader("엑셀 샘플")
        selected_idx = st.selectbox(
            "민원 선택",
            options=list(range(len(df))),
            format_func=lambda idx: sample_label(df, idx),
        )
        if st.button("선택 민원 불러오기", width="stretch"):
            set_sample(df, selected_idx)
            st.session_state.pop("last_result", None)
            st.rerun()

        st.dataframe(
            df.iloc[:, :2],
            width="stretch",
            hide_index=True,
            height=360,
        )

    with right:
        st.subheader("민원 입력")
        title = st.text_input("제목", key="complaint_title")
        body = st.text_area("본문", key="complaint_body", height=280)

        run_clicked = st.button("Supervisor 실행", type="primary", width="stretch")

    if run_clicked:
        st.session_state.pop("last_result", None)
        if not api_key.strip():
            st.error("OpenRouter API 키를 입력하세요.")
        elif not normalize_text(title) or not normalize_text(body):
            st.error("제목과 본문을 입력하세요.")
        else:
            result = run_pipeline(
                api_key=api_key,
                title=title,
                body=body,
                model_settings=model_settings,
                max_results=max_results,
                read_pages=read_pages,
            )
            if result:
                st.session_state["last_result"] = result
                render_results(result)
    elif "last_result" in st.session_state:
        render_results(st.session_state["last_result"])


if __name__ == "__main__":
    main()
