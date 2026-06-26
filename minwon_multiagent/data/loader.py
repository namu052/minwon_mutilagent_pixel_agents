"""민원 엑셀(민원신청번호/제목/본문) 로더."""
from __future__ import annotations

import html
from pathlib import Path

import openpyxl

from core.models import Minwon


def load_minwons(xlsx_path: str | Path) -> list[Minwon]:
    """엑셀 첫 시트에서 민원 목록을 읽어 Minwon 리스트로 반환한다.

    헤더 행(0): 민원신청번호 / 제목 / 본문 으로 가정한다.
    """
    path = Path(xlsx_path)
    if not path.exists():
        raise FileNotFoundError(f"엑셀 파일을 찾을 수 없습니다: {path}")

    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # openpyxl 내부 예외 포괄
        raise ValueError(f"엑셀을 열 수 없습니다: {exc}") from exc

    ws = wb.worksheets[0]
    minwons: list[Minwon] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # 헤더 스킵
        number, title, body = _row_to_fields(row)
        if not (number or title or body):
            continue
        minwons.append(
            Minwon(
                number=_clean(number),
                title=_clean(title),
                body=_clean(body),
            )
        )
    return minwons


def _row_to_fields(row: tuple) -> tuple:
    cells = list(row) + [None, None, None]
    return cells[0], cells[1], cells[2]


def _clean(value) -> str:
    if value is None:
        return ""
    return html.unescape(str(value)).strip()
