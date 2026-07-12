"""데이터 소스 추상화 — 지금은 Excel, 장기적으로 ERP API 확장점.

레코드 1건 = ``dict[str, str]`` (필드명 -> 값). 모든 소스는 ``records()`` 로
동일한 레코드 리스트를 낸다. ERP 연동 시 ``ErpApiDataSource`` 를 이 프로토콜에
맞춰 추가하기만 하면 엔진/GUI 변경 없이 붙는다.

**선택 프로토콜(포트 명세, RC-25).** 필수 3메서드(``records``/``fields``/
``field_labels``) 외에, 소스는 아래 선택 메서드를 선언해 소비자의 덕타이핑 추측을
대체할 수 있다 — 소비자는 ``getattr(src, "메서드", None)`` + ``callable`` 로만
탐지하고, 문자열 타입명 비교(``type(src).__name__``)로 소스 종류를 식별하지 않는다
(클래스 개명이 조용한 오기록이 되지 않게):

- ``source_pointer() -> str`` — 생성 원장에 남길 **포인터-온리** 소스 표기(쿼리·키·값
  박제 금지). 미선언 시 소비자가 ``path`` 속성(``file:<경로>``) → 타입명 순으로 강등
  표기한다(:meth:`hwpxfiller.gui.run_state.RunViewModel.source_pointer` 참조).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

Record = "dict[str, str]"


@runtime_checkable
class DataSource(Protocol):
    def records(self) -> "list[dict[str, str]]":
        """문서 생성용 레코드 목록을 반환한다."""
        ...

    def fields(self) -> "list[str]":
        """레코드가 제공하는 필드(컬럼) 이름 목록."""
        ...

    def field_labels(self) -> "dict[str, str]":
        """이 소스의 어휘: 소스 키 → 사람이 읽는 라벨(퍼지 자동제안의 타겟).

        키가 이미 사람 라벨인 소스(예: Excel/CSV 헤더)는 빈 dict 를 반환한다 —
        이것이 기본이다. 영문 코드 키를 쓰는 소스(예: 나라장터 API)만
        자기 어휘를 선언해 override 한다. "선택된 소스가 자기 어휘를 소유한다"
        는 원칙의 범용 이음새다(코어 ``mapping`` 은 어휘를 품지 않는다).
        """
        return {}
