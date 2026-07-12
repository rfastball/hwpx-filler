"""Excel 데이터 소스 (openpyxl).

가정: 첫 시트(또는 지정 시트)의 1행이 헤더(필드명), 이후 각 행이 문서 1건.
빈 행(모든 셀 공백)은 건너뛴다. CSV 도 동일 규약으로 지원.
"""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook


class ExcelDataSource:
    def __init__(self, path: str, sheet: "str | None" = None, header_row: int = 1):
        self.path = path
        self.sheet = sheet
        self.header_row = header_row
        self._headers: "list[str]" = []
        self._records: "list[dict[str, str]]" = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        ext = Path(self.path).suffix.lower()
        if ext == ".csv":
            self._load_csv()
        else:
            self._load_xlsx()
        self._loaded = True

    def _load_xlsx(self) -> None:
        wb = load_workbook(self.path, data_only=True, read_only=True)
        try:
            ws = wb[self.sheet] if self.sheet else wb[wb.sheetnames[0]]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        if len(rows) < self.header_row:
            return
        header = rows[self.header_row - 1]
        self._headers = [str(h).strip() if h is not None else "" for h in header]
        for raw in rows[self.header_row:]:
            self._append_record(raw)

    def _load_csv(self) -> None:
        with open(self.path, "r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        if len(rows) < self.header_row:
            return
        self._headers = [h.strip() for h in rows[self.header_row - 1]]
        for raw in rows[self.header_row:]:
            self._append_record(raw)

    def _append_record(self, raw) -> None:
        if raw is None:
            return
        cells = ["" if c is None else str(c) for c in raw]
        if all(c.strip() == "" for c in cells):
            return  # 빈 행 스킵
        rec: dict[str, str] = {}
        for i, head in enumerate(self._headers):
            if not head:
                continue
            rec[head] = cells[i] if i < len(cells) else ""
        self._records.append(rec)

    # ---------------------------------------------------------- DataSource
    def records(self) -> "list[dict[str, str]]":
        self._load()
        return self._records

    def fields(self) -> "list[str]":
        self._load()
        return [h for h in self._headers if h]

    def field_labels(self) -> "dict[str, str]":
        """Excel/CSV 헤더는 이미 사람이 읽는 라벨이라 별도 어휘가 없다(빈 dict).

        영문 코드 키를 쓰는 소스(예: 나라장터 API)만 자기 어휘를 선언한다.
        """
        return {}
