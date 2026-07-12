"""인라인(수기) DataSource — 파일 없이 메모리 레코드를 그대로 소스로 겨눈다.

txt 즉시 기안의 '수기 1건' 경로(UD-25)가 소비한다: 값 몇 개만 넣고 바로 복사한다는
즉시 기안의 핵심 가치를 위해 엑셀 파일 제작을 강제하지 않는다. 파일 소스
(:class:`~hwpxfiller.data.excel.ExcelDataSource`)와 동일한
:class:`~hwpxfiller.data.base.DataSource` 포트를 지켜 다운스트림(렌더·검수)이 소스
*종류*를 구별하지 않는다 — 종류 선택은 :func:`~hwpxfiller.data.factory.make_source`
(``kind="inline"``)에만 모인다.
"""
from __future__ import annotations


class InlineDataSource:
    """메모리 레코드 목록을 그대로 겨누는 소스 — 방어 복사로 외부 변형과 격리한다."""

    def __init__(self, records: "list[dict[str, str]]"):
        self._records = [dict(r) for r in records]

    def records(self) -> "list[dict[str, str]]":
        return [dict(r) for r in self._records]

    def fields(self) -> "list[str]":
        """등장 순서대로 유일 필드명 — 헤더 어휘가 이미 사람 라벨이라 별도 매핑 없음."""
        seen: "list[str]" = []
        for r in self._records:
            for k in r:
                if k not in seen:
                    seen.append(k)
        return seen

    def field_labels(self) -> "dict[str, str]":
        # 키가 이미 사람 라벨(수기 입력) — 소스 어휘 override 없음(base.py 기본과 동형).
        return {}
