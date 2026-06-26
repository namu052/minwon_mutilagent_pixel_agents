from __future__ import annotations

import html
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup


OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODELS = {
    "classification": "anthropic/claude-sonnet-4.6",
    "search": "anthropic/claude-sonnet-4.6",
    "writing": "anthropic/claude-sonnet-4.6",
    "review": "anthropic/claude-sonnet-4.6",
}

WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns an invalid or failed response."""


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        referer: str = "http://localhost:8501",
        title: str = "Civil Complaint Draft Multi-Agent",
    ) -> None:
        self.api_key = "".join(api_key.split())
        self.referer = referer
        self.title = title

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 3000,
    ) -> str:
        if not self.api_key:
            raise OpenRouterError("OpenRouter API 키가 비어 있습니다.")

        headers = {
            "Authorization": f"Bearer {self._validated_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._latin1_header(self.referer, "HTTP-Referer"),
            "X-Title": self._latin1_header(self.title, "X-Title"),
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = requests.post(
                OPENROUTER_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )
        except (requests.RequestException, UnicodeEncodeError) as exc:
            raise OpenRouterError(f"OpenRouter 호출 실패: {exc}") from exc

        if response.status_code >= 400:
            try:
                detail: Any = response.json()
            except ValueError:
                detail = response.text[:1000]
            raise OpenRouterError(f"OpenRouter 오류({response.status_code}): {detail}")

        try:
            data = response.json()
        except ValueError as exc:
            raise OpenRouterError("OpenRouter 응답을 JSON으로 해석할 수 없습니다.") from exc

        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError(f"OpenRouter 응답에 choices가 없습니다: {data}")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            return "\n".join(str(part.get("text", part)) for part in content)
        if content is None:
            raise OpenRouterError(f"OpenRouter 응답에 content가 없습니다: {data}")
        return str(content)

    def _validated_api_key(self) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._~:/+=-]+", self.api_key):
            raise OpenRouterError(
                "OpenRouter API 키에 허용되지 않는 문자가 포함되어 있습니다. "
                "https://openrouter.ai/keys 에서 발급한 sk-or-... 키만 다시 붙여넣어 주세요."
            )
        return self.api_key

    @staticmethod
    def _latin1_header(value: str, name: str) -> str:
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            return "Minwon Multi-Agent" if name == "X-Title" else value.encode("ascii", "ignore").decode("ascii")
        if name == "X-Title" and "?" in value:
            return "Minwon Multi-Agent"
        return value


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return html.unescape(str(value)).strip()


def compact_text(text: str, max_chars: int = 4000) -> str:
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n...[생략]"


def complaint_to_text(title: str, body: str) -> str:
    return f"제목: {normalize_text(title)}\n본문:\n{normalize_text(body)}"


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = [cleaned]
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return {"raw_text": text}


def _json_for_prompt(data: Any, max_chars: int = 14000) -> str:
    return compact_text(json.dumps(data, ensure_ascii=False, indent=2), max_chars)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;/\n]", value) if part.strip()]
    return [value]


def classify_complaint(
    client: OpenRouterClient,
    *,
    title: str,
    body: str,
    model: str = DEFAULT_MODELS["classification"],
) -> tuple[dict[str, Any], dict[str, Any]]:
    complaint_text = complaint_to_text(title, body)
    messages = [
        {
            "role": "system",
            "content": (
                "너는 대한민국 공공기관 민원 분류 Agent다. "
                "민원 원문만 보고 담당 부서와 민원 유형을 판별한다. "
                "불확실하면 가장 가능성이 높은 부서와 이유를 쓰고, JSON만 출력한다."
            ),
        },
        {
            "role": "user",
            "content": f"""
다음 민원을 분류하라.

분류 기준:
- 부서는 실제 처리 가능성이 높은 중앙부처, 지자체, 소속기관, 센터 단위로 쓴다.
- 유형은 예: 채용/시험, 임용/승진/전보, 복무/휴가/휴직, 보수/수당/여비, 징계/비위, 공무상 재해, 정보공개/자료요청, 기관운영/서비스 불만, 정책의견/제안, 기타 중에서 고르되 더 적합한 명칭이 있으면 써도 된다.
- 검색_Agent가 바로 쓸 수 있도록 핵심 검색어를 3~7개 제시한다.

민원:
{complaint_text}

출력 JSON 스키마:
{{
  "department": "판별된 부서",
  "department_reason": "부서 판별 이유",
  "complaint_type": "판별된 유형",
  "type_reason": "유형 판별 이유",
  "confidence": 0.0,
  "keywords": ["검색어1", "검색어2"],
  "handoff_summary": "검색_Agent에 전달할 한 문장 요약"
}}
""".strip(),
        },
    ]

    raw = client.chat(model=model, messages=messages, temperature=0.1, max_tokens=1800)
    parsed = parse_json_object(raw)

    department = normalize_text(parsed.get("department") or parsed.get("판별된_부서") or "분류 필요")
    complaint_type = normalize_text(
        parsed.get("complaint_type") or parsed.get("type") or parsed.get("판별된_유형") or "유형 분류 필요"
    )
    keywords = [normalize_text(item) for item in _as_list(parsed.get("keywords")) if normalize_text(item)]

    result = {
        "department": department,
        "department_reason": normalize_text(parsed.get("department_reason")),
        "complaint_type": complaint_type,
        "type_reason": normalize_text(parsed.get("type_reason")),
        "confidence": parsed.get("confidence", ""),
        "keywords": keywords,
        "handoff_summary": normalize_text(parsed.get("handoff_summary")),
        "llm_raw": raw,
    }

    handoff = {
        "민원_원문": complaint_text,
        "판별된_부서": department,
        "판별된_유형": complaint_type,
        "분류_요약": result["handoff_summary"],
        "검색_키워드": keywords,
    }
    return result, handoff


def _fallback_terms(handoff: dict[str, Any]) -> list[str]:
    text = normalize_text(handoff.get("민원_원문"))
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    stopwords = {
        "안녕",
        "합니다",
        "문의",
        "답변",
        "관련",
        "궁금",
        "가능",
        "여부",
        "민원",
        "감사",
    }
    terms: list[str] = []
    for word in words:
        if word in stopwords or word in terms:
            continue
        terms.append(word)
        if len(terms) >= 6:
            break
    return terms


def build_search_queries(handoff: dict[str, Any]) -> dict[str, list[str]]:
    keywords = [normalize_text(item) for item in _as_list(handoff.get("검색_키워드")) if normalize_text(item)]
    if not keywords:
        keywords = _fallback_terms(handoff)

    department = normalize_text(handoff.get("판별된_부서"))
    complaint_type = normalize_text(handoff.get("판별된_유형"))
    key_terms = " ".join(keywords[:5]).strip() or complaint_type
    context = " ".join(part for part in [department, complaint_type, key_terms] if part).strip()

    law_queries = [
        f"{context} 관련 법령",
        f"국가법령정보센터 {key_terms}",
        f"site:law.go.kr {key_terms}",
    ]
    answer_queries = [
        f"{context} 질의 답변",
        f"{key_terms} 민원 답변",
        f"site:epeople.go.kr {key_terms}",
        f"site:mpm.go.kr {key_terms} 질의 답변",
    ]

    return {
        "law": _dedupe(law_queries),
        "past_answer": _dedupe(answer_queries),
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _clean_duckduckgo_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return href


def duckduckgo_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query, "kl": "kr-kr"},
            headers=WEB_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict[str, str]] = []

    for node in soup.select(".result"):
        link = node.select_one(".result__a")
        if not link:
            continue
        url = _clean_duckduckgo_url(link.get("href", ""))
        title = normalize_text(link.get_text(" ", strip=True))
        snippet_node = node.select_one(".result__snippet")
        snippet = normalize_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
        if not url or not title:
            continue
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break

    return results


def fetch_page_excerpt(url: str, *, max_chars: int = 1600) -> str:
    if url.lower().split("?")[0].endswith(".pdf"):
        return "PDF 문서는 검색 결과 요약만 사용했습니다."

    try:
        response = requests.get(url, headers=WEB_HEADERS, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type:
        return "PDF 문서는 검색 결과 요약만 사용했습니다."
    if "text/html" not in content_type and "application/xhtml" not in content_type and content_type:
        return ""

    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    text = "\n".join(part for part in (normalize_text(s) for s in soup.stripped_strings) if part)
    return compact_text(text, max_chars)


def collect_web_sources(
    queries: list[str],
    *,
    kind: str,
    max_results: int,
    read_pages: bool,
) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for query in queries:
        for result in duckduckgo_search(query, max_results=max_results):
            url = result["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            source = {
                "kind": kind,
                "query": query,
                "title": result["title"],
                "url": url,
                "snippet": result.get("snippet", ""),
                "excerpt": fetch_page_excerpt(url) if read_pages else "",
            }
            sources.append(source)
            if len(sources) >= max_results:
                break
        if len(sources) >= max_results:
            break

    return sources


def search_references(
    client: OpenRouterClient,
    *,
    classification_handoff: dict[str, Any],
    model: str = DEFAULT_MODELS["search"],
    max_results_per_category: int = 5,
    read_pages: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    queries = build_search_queries(classification_handoff)
    law_sources = collect_web_sources(
        queries["law"],
        kind="law",
        max_results=max_results_per_category,
        read_pages=read_pages,
    )
    past_answer_sources = collect_web_sources(
        queries["past_answer"],
        kind="past_answer",
        max_results=max_results_per_category,
        read_pages=read_pages,
    )
    source_bundle = {
        "law_sources": law_sources,
        "past_answer_sources": past_answer_sources,
    }

    messages = [
        {
            "role": "system",
            "content": (
                "너는 웹검색 결과를 검토하는 검색_Agent다. "
                "제공된 웹검색 결과에 근거해 관련 법령과 과거 답변 원칙을 추린다. "
                "검색 결과에 없는 조문명, 기관 답변, 사실은 단정하지 않는다. JSON만 출력한다."
            ),
        },
        {
            "role": "user",
            "content": f"""
1단계 핸드오프:
{_json_for_prompt(classification_handoff, 6000)}

웹검색 결과:
{_json_for_prompt(source_bundle, 18000)}

작업:
- 관련성이 높은 법령 근거를 최대 5개 정리한다.
- 관련 과거 답변 또는 기관 안내의 답변 원칙을 최대 5개 요약한다.
- 근거가 부족하거나 원문 확인이 필요한 부분은 limitations에 적는다.

출력 JSON 스키마:
{{
  "law_basis": [
    {{
      "label": "근거1",
      "law_name": "법령명 또는 지침명",
      "article": "조문/항목",
      "basis_text": "민원 답변에 쓸 핵심 근거",
      "source_title": "출처 제목",
      "source_url": "출처 URL",
      "relevance": "관련성"
    }}
  ],
  "past_answer_summaries": [
    {{
      "label": "답변1",
      "summary": "과거 답변 또는 안내 요약",
      "answering_principle": "이번 민원 답변에 적용할 원칙",
      "source_title": "출처 제목",
      "source_url": "출처 URL"
    }}
  ],
  "limitations": ["검색 한계 또는 확인 필요 사항"]
}}
""".strip(),
        },
    ]

    raw = client.chat(model=model, messages=messages, temperature=0.1, max_tokens=2600)
    parsed = parse_json_object(raw)

    law_basis = _as_list(parsed.get("law_basis"))
    past_summaries = _as_list(parsed.get("past_answer_summaries"))
    limitations = [normalize_text(item) for item in _as_list(parsed.get("limitations")) if normalize_text(item)]

    result = {
        "search_queries": queries,
        "law_basis": law_basis,
        "past_answer_summaries": past_summaries,
        "limitations": limitations,
        "sources": source_bundle,
        "llm_raw": raw,
    }
    handoff = {
        "법령근거": law_basis,
        "과거_답변_요약": past_summaries,
        "검색_한계": limitations,
    }
    return result, handoff


def draft_answer(
    client: OpenRouterClient,
    *,
    classification_handoff: dict[str, Any],
    search_handoff: dict[str, Any],
    model: str = DEFAULT_MODELS["writing"],
) -> tuple[dict[str, Any], dict[str, Any]]:
    messages = [
        {
            "role": "system",
            "content": (
                "너는 공공기관 민원 답변 초안을 작성하는 작성_Agent다. "
                "검색_Agent가 넘긴 법령근거와 과거 답변 요약만 근거로 사용한다. "
                "근거가 약한 부분은 단정하지 않고 확인 필요로 표현한다. JSON만 출력한다."
            ),
        },
        {
            "role": "user",
            "content": f"""
1단계 핸드오프:
{_json_for_prompt(classification_handoff, 7000)}

2단계 핸드오프:
{_json_for_prompt(search_handoff, 12000)}

작성 기준:
- 공공기관 민원 답변 말투로 작성한다.
- 시작 인사, 민원 요지, 검토 근거, 답변, 추가 안내 순서로 구성한다.
- 모든 법령/과거답변 근거는 [근거1], [답변1]처럼 본문 안에 인용한다.
- 검색 한계가 있으면 마지막에 담당 부서 확인 필요 사항으로 정리한다.

출력 JSON 스키마:
{{
  "draft": "근거 인용을 포함한 답변 초안",
  "used_citations": ["근거1", "답변1"],
  "handoff_summary": "검수_Agent에 전달할 요약"
}}
""".strip(),
        },
    ]

    raw = client.chat(model=model, messages=messages, temperature=0.25, max_tokens=3200)
    parsed = parse_json_object(raw)
    draft = normalize_text(parsed.get("draft") or raw)

    result = {
        "draft": draft,
        "used_citations": [normalize_text(item) for item in _as_list(parsed.get("used_citations"))],
        "handoff_summary": normalize_text(parsed.get("handoff_summary")),
        "llm_raw": raw,
    }
    handoff = {
        "근거_인용을_포함한_답변_초안": draft,
        "사용한_근거": result["used_citations"],
        "작성_요약": result["handoff_summary"],
    }
    return result, handoff


def review_answer(
    client: OpenRouterClient,
    *,
    classification_handoff: dict[str, Any],
    search_handoff: dict[str, Any],
    draft_handoff: dict[str, Any],
    model: str = DEFAULT_MODELS["review"],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "너는 공공기관 민원 답변 검수_Agent다. "
                "말투, 정확성, 근거 인용 적정성을 점검하고 필요하면 최종안을 보정한다. "
                "제공된 근거 밖의 새로운 법령이나 사실은 추가하지 않는다. JSON만 출력한다."
            ),
        },
        {
            "role": "user",
            "content": f"""
1단계 핸드오프:
{_json_for_prompt(classification_handoff, 7000)}

2단계 핸드오프:
{_json_for_prompt(search_handoff, 12000)}

3단계 핸드오프:
{_json_for_prompt(draft_handoff, 12000)}

검수 기준:
- 말투: 민원인에게 공손하고 방어적/감정적 표현이 없는지 확인한다.
- 정확성: 원문 질문에 답하고 있는지, 단정하면 안 되는 부분을 단정하지 않았는지 확인한다.
- 근거: 본문 인용이 2단계 근거와 대응되는지 확인한다.

출력 JSON 스키마:
{{
  "tone_check": {{"status": "pass 또는 revise", "comment": "검수 의견"}},
  "accuracy_check": {{"status": "pass 또는 revise", "comment": "검수 의견"}},
  "basis_check": {{"status": "pass 또는 revise", "comment": "검수 의견"}},
  "issues": ["수정 또는 확인 필요 사항"],
  "final_answer": "검수 반영 최종 답변안",
  "basis_audit": ["근거 인용 점검 결과"]
}}
""".strip(),
        },
    ]

    raw = client.chat(model=model, messages=messages, temperature=0.15, max_tokens=3600)
    parsed = parse_json_object(raw)
    final_answer = normalize_text(
        parsed.get("final_answer") or draft_handoff.get("근거_인용을_포함한_답변_초안") or raw
    )

    return {
        "tone_check": parsed.get("tone_check", {}),
        "accuracy_check": parsed.get("accuracy_check", {}),
        "basis_check": parsed.get("basis_check", {}),
        "issues": _as_list(parsed.get("issues")),
        "final_answer": final_answer,
        "basis_audit": _as_list(parsed.get("basis_audit")),
        "llm_raw": raw,
    }


@dataclass(frozen=True)
class SupervisorTool:
    name: str
    agent: str
    description: str
    requires: list[str]
    provides: list[str]


@dataclass
class PixelAgentState:
    """Streamlit용으로 경량화한 pixel-agents AgentState."""

    id: int
    name: str
    role: str
    model: str
    status: str = "waiting"
    active_tool_id: str = ""
    active_tool_name: str = ""
    last_message: str = "대기 중"
    outputs: list[str] = field(default_factory=list)


class PixelAgentStateStore:
    """pixel-agents의 AgentStateStore/broadcast 흐름을 민원 앱에 맞게 축소한 저장소."""

    def __init__(self) -> None:
        self.session_id = f"minwon-{uuid.uuid4().hex[:8]}"
        self._agents: dict[int, PixelAgentState] = {}
        self._tool_to_agent: dict[str, int] = {}
        self._events: list[dict[str, Any]] = []
        self._seq = 0

    def add_agent(self, tool: SupervisorTool, model: str) -> None:
        agent_id = len(self._agents) + 1
        agent = PixelAgentState(
            id=agent_id,
            name=tool.agent,
            role=tool.description,
            model=model,
        )
        self._agents[agent_id] = agent
        self._tool_to_agent[tool.name] = agent_id
        self.broadcast(
            {
                "type": "agentCreated",
                "id": agent_id,
                "agent": agent.name,
                "toolName": tool.name,
                "model": model,
            }
        )

    def start_tool(self, tool: SupervisorTool) -> str:
        agent = self._agent_for_tool(tool)
        tool_id = f"{tool.name}-{self._seq + 1}"
        agent.status = "active"
        agent.active_tool_id = tool_id
        agent.active_tool_name = tool.name
        agent.last_message = f"{tool.agent} 실행 중"
        self.broadcast(
            {
                "type": "agentToolStart",
                "id": agent.id,
                "toolId": tool_id,
                "toolName": tool.name,
                "status": agent.last_message,
            }
        )
        self.broadcast({"type": "agentStatus", "id": agent.id, "status": "active"})
        return tool_id

    def complete_tool(
        self,
        tool: SupervisorTool,
        *,
        tool_id: str,
        display_label: str,
        output_keys: list[str],
    ) -> None:
        agent = self._agent_for_tool(tool)
        agent.status = "waiting"
        agent.active_tool_id = ""
        agent.active_tool_name = ""
        agent.last_message = display_label
        agent.outputs = output_keys
        self.broadcast({"type": "agentToolDone", "id": agent.id, "toolId": tool_id})
        self.broadcast({"type": "agentToolsClear", "id": agent.id})
        self.broadcast(
            {
                "type": "handoffProduced",
                "id": agent.id,
                "toolName": tool.name,
                "label": display_label,
                "outputs": output_keys,
            }
        )
        self.broadcast({"type": "agentStatus", "id": agent.id, "status": "waiting"})

    def fail_tool(self, tool: SupervisorTool, *, tool_id: str, error: str) -> None:
        agent = self._agent_for_tool(tool)
        agent.status = "error"
        agent.active_tool_id = ""
        agent.active_tool_name = ""
        agent.last_message = error
        self.broadcast(
            {
                "type": "agentToolError",
                "id": agent.id,
                "toolId": tool_id,
                "toolName": tool.name,
                "error": error,
            }
        )
        self.broadcast({"type": "agentStatus", "id": agent.id, "status": "error"})

    def broadcast(self, message: dict[str, Any]) -> None:
        self._seq += 1
        self._events.append(
            {
                "seq": self._seq,
                "time": time.strftime("%H:%M:%S"),
                **message,
            }
        )

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agents": [asdict(agent) for agent in self._agents.values()],
            "events": list(self._events),
        }

    def _agent_for_tool(self, tool: SupervisorTool) -> PixelAgentState:
        return self._agents[self._tool_to_agent[tool.name]]


class ComplaintSupervisor:
    """Supervisor(as tool) runner that exposes each agent as a callable tool."""

    def __init__(
        self,
        client: OpenRouterClient,
        *,
        model_settings: dict[str, str] | None = None,
        max_results_per_category: int = 5,
        read_pages: bool = True,
    ) -> None:
        self.client = client
        self.model_settings = {**DEFAULT_MODELS, **(model_settings or {})}
        self.max_results_per_category = max_results_per_category
        self.read_pages = read_pages
        self.tools = [
            SupervisorTool(
                name="classification_agent_tool",
                agent="분류_Agent",
                description="민원 원문을 받아 담당 부서, 민원 유형, 검색 키워드를 판별한다.",
                requires=["input.title", "input.body"],
                provides=["classification", "handoffs.classification_to_search"],
            ),
            SupervisorTool(
                name="search_agent_tool",
                agent="검색_Agent",
                description="분류 결과를 기반으로 웹검색을 수행하고 법령근거와 과거 답변 요약을 정리한다.",
                requires=["handoffs.classification_to_search"],
                provides=["search", "handoffs.search_to_writing"],
            ),
            SupervisorTool(
                name="writing_agent_tool",
                agent="작성_Agent",
                description="검색된 근거와 과거 답변 요약을 바탕으로 근거 인용 포함 답변 초안을 작성한다.",
                requires=["handoffs.classification_to_search", "handoffs.search_to_writing"],
                provides=["draft", "handoffs.writing_to_review"],
            ),
            SupervisorTool(
                name="review_agent_tool",
                agent="검수_Agent",
                description="답변 초안의 말투, 정확성, 근거 대응성을 검수하고 최종 답변안을 만든다.",
                requires=[
                    "handoffs.classification_to_search",
                    "handoffs.search_to_writing",
                    "handoffs.writing_to_review",
                ],
                provides=["review"],
            ),
        ]
        self._tool_map = {tool.name: tool for tool in self.tools}
        self._tool_model_keys = {
            "classification_agent_tool": "classification",
            "search_agent_tool": "search",
            "writing_agent_tool": "writing",
            "review_agent_tool": "review",
        }
        self.runtime = PixelAgentStateStore()
        for tool in self.tools:
            self.runtime.add_agent(tool, self.model_settings[self._tool_model_keys[tool.name]])

    def initial_state(self, *, title: str, body: str) -> dict[str, Any]:
        return {
            "input": {"title": title, "body": body},
            "classification": None,
            "search": None,
            "draft": None,
            "review": None,
            "handoffs": {},
            "supervisor": {
                "mode": "Supervisor(as tool)",
                "policy": "Supervisor가 등록된 Agent 도구를 순차 호출하고 공유 상태를 갱신한다.",
                "tool_registry": [asdict(tool) for tool in self.tools],
                "trace": [],
            },
        }

    def invoke_tool(
        self,
        tool_name: str,
        state: dict[str, Any],
        *,
        on_runtime_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if tool_name not in self._tool_map:
            raise ValueError(f"등록되지 않은 Supervisor 도구입니다: {tool_name}")

        tool = self._tool_map[tool_name]
        tool_id = self.runtime.start_tool(tool)
        if on_runtime_event:
            on_runtime_event(self.runtime.to_snapshot())
        try:
            if tool_name == "classification_agent_tool":
                display_label = "1단계 -> 2단계 핸드오프"
                result, handoff = classify_complaint(
                    self.client,
                    title=state["input"]["title"],
                    body=state["input"]["body"],
                    model=self.model_settings["classification"],
                )
                state["classification"] = result
                state["handoffs"]["classification_to_search"] = handoff
                display_payload: Any = handoff

            elif tool_name == "search_agent_tool":
                display_label = "2단계 -> 3단계 핸드오프"
                result, handoff = search_references(
                    self.client,
                    classification_handoff=state["handoffs"]["classification_to_search"],
                    model=self.model_settings["search"],
                    max_results_per_category=self.max_results_per_category,
                    read_pages=self.read_pages,
                )
                state["search"] = result
                state["handoffs"]["search_to_writing"] = handoff
                display_payload = handoff

            elif tool_name == "writing_agent_tool":
                display_label = "3단계 -> 4단계 핸드오프"
                result, handoff = draft_answer(
                    self.client,
                    classification_handoff=state["handoffs"]["classification_to_search"],
                    search_handoff=state["handoffs"]["search_to_writing"],
                    model=self.model_settings["writing"],
                )
                state["draft"] = result
                state["handoffs"]["writing_to_review"] = handoff
                display_payload = handoff

            else:
                display_label = "최종 검수 결과"
                result = review_answer(
                    self.client,
                    classification_handoff=state["handoffs"]["classification_to_search"],
                    search_handoff=state["handoffs"]["search_to_writing"],
                    draft_handoff=state["handoffs"]["writing_to_review"],
                    model=self.model_settings["review"],
                )
                state["review"] = result
                display_payload = {
                    "tone_check": result["tone_check"],
                    "accuracy_check": result["accuracy_check"],
                    "basis_check": result["basis_check"],
                    "issues": result["issues"],
                }
        except Exception as exc:
            self.runtime.fail_tool(tool, tool_id=tool_id, error=str(exc))
            if on_runtime_event:
                on_runtime_event(self.runtime.to_snapshot())
            raise

        self.runtime.complete_tool(
            tool,
            tool_id=tool_id,
            display_label=display_label,
            output_keys=tool.provides,
        )
        if on_runtime_event:
            on_runtime_event(self.runtime.to_snapshot())

        trace_event = {
            "step": len(state["supervisor"]["trace"]) + 1,
            "tool_name": tool.name,
            "agent": tool.agent,
            "requires": tool.requires,
            "provides": tool.provides,
            "display_label": display_label,
            "runtime_tool_id": tool_id,
        }
        state["supervisor"]["trace"].append(trace_event)

        return {
            "tool": asdict(tool),
            "trace_event": trace_event,
            "display_label": display_label,
            "display_payload": display_payload,
        }

    def to_result(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "architecture": "Supervisor(as tool)",
            "supervisor": state["supervisor"],
            "classification": state["classification"],
            "search": state["search"],
            "draft": state["draft"],
            "review": state["review"],
            "handoffs": state["handoffs"],
            "pixel_runtime": self.runtime.to_snapshot(),
        }
