"""DataSource 팩토리 — 소스 *종류* 선택을 한 곳에 모은다.

GUI·ViewModel 은 구체 클래스(``ExcelDataSource`` 등)를 직접 만들지 않고 여기를 거친다.
누적치환·나라장터·API 직결 같은 미래 소스 종류는 이 팩토리에만 추가되면 되고,
소비자(위저드·실행 뷰모델)는 :class:`~hwpxfiller.data.base.DataSource` 포트만 알면 된다
— UI/VM 코드 수정 없이 종류가 늘어난다.
"""
from __future__ import annotations

from pathlib import Path

from .base import DataSource
from .excel import ExcelDataSource

# 파일 겨눔으로 여는 소스의 확장자(현재 Excel 어댑터가 xlsx/xlsm/csv 를 함께 처리).
_EXCEL_EXTS = {".xlsx", ".xlsm", ".csv"}


def source_for_path(path: "str | Path", **opts) -> DataSource:
    """파일 경로 확장자로 적절한 파일형 DataSource 를 만든다.

    현행: xlsx/xlsm/csv → :class:`ExcelDataSource`. 지원하지 않는 확장자는
    ``ValueError`` — 소비자가 사용자에게 시끄럽게 알린다(조용한 실패 금지).
    """
    ext = Path(path).suffix.lower()
    if ext in _EXCEL_EXTS:
        return ExcelDataSource(str(path), **opts)
    raise ValueError(f"지원하지 않는 데이터 파일 형식입니다: {ext or '(확장자 없음)'}")


def make_source(kind: str, **opts) -> DataSource:
    """소스 *종류* 이름으로 DataSource 를 만든다(파일 아닌 종류 포함).

    - ``"excel"``  — ``path=`` (+ 선택 ``sheet``/``header_row``)
    - ``"nara"``   — ``service_key=``·``bgn_dt=``·``end_dt=`` … (조달청 표준 취득)

    미래 종류(``"cumulative"`` 등)는 여기에 분기만 추가한다.
    """
    if kind == "excel":
        return ExcelDataSource(**opts)
    if kind == "nara":
        from .nara import NaraStdDataSource

        return NaraStdDataSource(**opts)
    raise ValueError(f"알 수 없는 데이터 소스 종류입니다: {kind!r}")
