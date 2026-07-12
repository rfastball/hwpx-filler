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


def source_from_pool_item(item, *, secret_store=None, fetcher=None) -> DataSource:
    """데이터셋 풀 항목(``kind`` + ``opts`` 참조)을 실 :class:`DataSource` 로 복원한다.

    풀 항목은 **참조만** 담는다(레코드·비밀 없음) — 복원이 실행 시점의 "재읽기(싱크)"다.
    나라장터 항목은 **opts 에 ServiceKey 가 없으므로** 이 순간 OS 자격증명 저장소(N1
    SecretStore)에서 키를 읽어 주입한다(``gui/nara_state.py`` acquire 의 "키는 이 순간에만
    읽어 넘김" 패턴 미러). 키 미등록은 **시끄럽게** 실패시킨다(조용한 빈 취득 금지).

    아이템은 **덕타입**(``.kind``/``.opts``)으로만 읽어 ``data``→``core`` 역의존을 만들지 않는다.
    ``fetcher`` 는 나라 소스에 그대로 전달(테스트 주입 — 네트워크 없이 복원 검증).
    """
    kind = item.kind
    opts = dict(item.opts)
    if kind == "nara":
        from .secret_store import NARA_SERVICE_KEY_NAME, default_secret_store

        store = secret_store if secret_store is not None else default_secret_store()
        key = store.get(NARA_SERVICE_KEY_NAME)
        if not key:
            raise ValueError(
                "나라장터 데이터셋을 복원하려면 서비스키가 필요합니다 — 풀 항목엔 키가 "
                "저장되지 않습니다. 먼저 키를 등록하세요."
            )
        return make_source("nara", service_key=key, fetcher=fetcher, **opts)
    return make_source(kind, **opts)
