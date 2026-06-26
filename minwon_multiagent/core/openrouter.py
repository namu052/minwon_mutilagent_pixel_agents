"""OpenRouter Chat Completions 클라이언트 (OpenAI 호환).

웹검색은 OpenRouter의 web 플러그인(`plugins=[{"id": "web"}]`)으로 처리한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from .config import (
    APP_REFERER,
    APP_TITLE,
    CHAT_COMPLETIONS_URL,
    REQUEST_TIMEOUT_SEC,
)
from .models import Citation


class OpenRouterError(RuntimeError):
    """OpenRouter 호출 실패 시 발생."""


@dataclass(frozen=True)
class ChatResponse:
    content: str
    citations: tuple[Citation, ...]


class OpenRouterClient:
    """API 키를 보관하고 채팅 요청을 보내는 얇은 래퍼."""

    def __init__(self, api_key: str):
        if not api_key or not api_key.strip():
            raise OpenRouterError("OpenRouter API 키가 비어 있습니다.")
        self._api_key = "".join(api_key.split())

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._validated_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._latin1_header(APP_REFERER, "HTTP-Referer"),
            "X-Title": self._latin1_header(APP_TITLE, "X-Title"),
        }

    def chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        web_search: bool = False,
        max_web_results: int = 5,
    ) -> ChatResponse:
        """단일 채팅 요청을 보내고 응답 본문/출처를 반환한다."""
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if web_search:
            payload["plugins"] = [{"id": "web", "max_results": max_web_results}]

        data = self._post(payload, model)
        return self._parse(data)

    def _post(self, payload: dict, model: str) -> dict:
        try:
            resp = requests.post(
                CHAT_COMPLETIONS_URL,
                headers=self._headers(),
                json=payload,
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except (requests.RequestException, UnicodeEncodeError) as exc:
            raise OpenRouterError(f"네트워크 오류({model}): {exc}") from exc

        if resp.status_code != 200:
            raise OpenRouterError(
                f"OpenRouter 오류 {resp.status_code} ({model}): {resp.text[:500]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise OpenRouterError(f"응답 JSON 파싱 실패({model}): {exc}") from exc

    @staticmethod
    def _parse(data: dict) -> ChatResponse:
        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError(f"빈 응답입니다: {str(data)[:300]}")

        message = choices[0].get("message", {})
        content = (message.get("content") or "").strip()
        citations = OpenRouterClient._extract_citations(message)
        return ChatResponse(content=content, citations=citations)

    def _validated_api_key(self) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._~:/+=-]+", self._api_key):
            raise OpenRouterError(
                "OpenRouter API 키에 허용되지 않는 문자가 포함되어 있습니다. "
                "https://openrouter.ai/keys 에서 발급한 sk-or-... 키만 다시 붙여넣어 주세요."
            )
        return self._api_key

    @staticmethod
    def _latin1_header(value: str, name: str) -> str:
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            return "Minwon Multi-Agent" if name == "X-Title" else value.encode("ascii", "ignore").decode("ascii")
        if name == "X-Title" and "?" in value:
            return "Minwon Multi-Agent"
        return value

    @staticmethod
    def _extract_citations(message: dict) -> tuple[Citation, ...]:
        annotations = message.get("annotations") or []
        out: list[Citation] = []
        for ann in annotations:
            if ann.get("type") != "url_citation":
                continue
            cite = ann.get("url_citation", {})
            url = cite.get("url")
            if not url:
                continue
            out.append(Citation(title=cite.get("title") or url, url=url))
        return tuple(out)
