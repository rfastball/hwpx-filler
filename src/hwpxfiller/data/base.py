"""데이터 소스 추상화 — 지금은 Excel, 장기적으로 ERP API 확장점.

레코드 1건 = ``dict[str, str]`` (필드명 -> 값). 모든 소스는 ``records()`` 로
동일한 레코드 리스트를 낸다. ERP 연동 시 ``ErpApiDataSource`` 를 이 프로토콜에
맞춰 추가하기만 하면 엔진/GUI 변경 없이 붙는다.
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
