# 민원 초안 생성 Supervisor(as tool)

`1782341096215_file.xlsx`의 민원 샘플을 불러와 Supervisor가 4개의 Agent 도구를 호출하면서 민원 답변 초안을 생성하는 Streamlit 앱입니다.

`pixel-agents`를 리버스 엔지니어링해 확인한 핵심 흐름(AgentStateStore → Runtime → event/broadcast → UI)을 Streamlit에 맞게 경량 구현했습니다. 실제 LLM 호출은 Claude Code CLI가 아니라 OpenRouter의 Anthropic Claude 모델을 사용합니다.

저장소에는 실행에 필요한 Streamlit 앱, 민원 샘플 엑셀, Supervisor/Agent 구현, Pixel Runtime 표시용 PNG asset, 시연 영상이 함께 포함됩니다. 원본 `pixel-agents` 전체 저장소는 포함하지 않고, 앱이 사용하는 최소 asset만 `assets/pixel_office/`에 번들했습니다.

## 실행

```powershell
pip install -r requirements.txt
streamlit run app.py
```

OpenRouter API Key는 앱 왼쪽 설정 영역에서 입력합니다.

## 포함된 앱

- 루트 `app.py`: Supervisor가 4개 Agent 도구를 호출하는 과제 제출용 메인 앱입니다.
- `complaint_agents.py`: OpenRouter 호출, Agent별 프롬프트, Supervisor 상태 관리, Pixel Runtime 이벤트 저장소를 포함합니다.
- `assets/pixel_office/`: Pixel Runtime 화면에 사용하는 배경, 캐릭터, 가구 PNG asset입니다.
- `minwon_multiagent/`: 4단계 민원 초안 생성 파이프라인을 별도 패키지 구조로 정리한 참고 구현입니다.
- `민원초안생성_PIXEL_AGENTS.mp4`: 앱 실행 결과를 보여주는 시연 영상입니다.

## Supervisor(as tool) 구조

기존 구조는 `app.py`가 각 Agent를 직접 순차 호출하는 방식이었습니다. 현재 구조는 `ComplaintSupervisor`가 각 Agent를 도구로 등록하고, Supervisor가 도구 호출 순서와 공유 상태를 관리합니다.

| Supervisor 도구 | 실제 Agent | 기본 OpenRouter 모델 | 입력 상태 | 출력 상태 |
| --- | --- | --- | --- | --- |
| `classification_agent_tool` | 분류_Agent | `anthropic/claude-sonnet-4.6` | 민원 제목, 본문 | 분류 결과, 1단계 핸드오프 |
| `search_agent_tool` | 검색_Agent | `anthropic/claude-sonnet-4.6` | 1단계 핸드오프 | 검색 결과, 2단계 핸드오프 |
| `writing_agent_tool` | 작성_Agent | `anthropic/claude-sonnet-4.6` | 1단계/2단계 핸드오프 | 답변 초안, 3단계 핸드오프 |
| `review_agent_tool` | 검수_Agent | `anthropic/claude-sonnet-4.6` | 1단계/2단계/3단계 핸드오프 | 검수 결과, 최종 답변안 |

## Pixel-agent식 런타임 매핑

| pixel-agents 개념 | 민원 앱 구현 |
| --- | --- |
| `AgentStateStore` | `PixelAgentStateStore`가 4개 민원 Agent 상태와 이벤트를 보관 |
| `AgentRuntime` | `ComplaintSupervisor.invoke_tool()`이 도구 시작/완료/실패 이벤트를 발생 |
| `ServerMessage` broadcast | `agentCreated`, `agentToolStart`, `agentToolDone`, `agentStatus`, `handoffProduced` 이벤트 로그 |
| Webview office UI | Streamlit의 `Pixel Runtime` 탭과 실행 중 상태 카드 |

## 워크플로우

```text
사용자 입력 또는 엑셀 샘플 선택
        ↓
Supervisor 초기 상태 생성
        ↓
classification_agent_tool 호출
        ↓
search_agent_tool 호출
        ↓
writing_agent_tool 호출
        ↓
review_agent_tool 호출
        ↓
최종 답변안 + Supervisor trace + 전체 핸드오프 표시
        ↓
Pixel Runtime 이벤트 로그 표시
```

## UI 표시 항목

- Supervisor 도구 호출 진행 상태
- Pixel Runtime 에이전트 상태 카드와 broadcast 이벤트 로그
- 각 도구의 입력 상태와 출력 상태
- 단계별 핸드오프 JSON
- 웹검색 출처
- 최종 답변안
- 전체 결과 JSON 다운로드
