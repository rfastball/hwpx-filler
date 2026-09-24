"""레코드 선택 상태 모델 — Qt 비의존 순수 파이썬(헤드리스 단위 테스트 대상).

메일머지의 수신자 리스트에 해당한다: N개 레코드 중 어떤 것을 생성 대상으로 삼을지.
기본은 **전체 선택**(조용한 빈 출력을 피함) — 단 뷰는 선택 수를 노출해 명시적으로 둔다.
``selected_records`` 는 원본 순서를 보존하므로 파일명 충돌 접미사가 결정적으로 유지된다.
"""

from __future__ import annotations


class SelectionModel:
    """레코드 인덱스별 선택 여부. 뷰(record_select)는 이 API 만 호출한다."""

    def __init__(self, count: int, all_selected: bool = True):
        self._selected: "list[bool]" = [all_selected] * count

    def __len__(self) -> int:
        return len(self._selected)

    def set_all(self) -> None:
        self._selected = [True] * len(self._selected)

    def set_none(self) -> None:
        self._selected = [False] * len(self._selected)

    def toggle(self, index: int, value: "bool | None" = None) -> None:
        self._selected[index] = (not self._selected[index]) if value is None else value

    def is_selected(self, index: int) -> bool:
        return self._selected[index]

    def selected_indices(self) -> "list[int]":
        return [i for i, s in enumerate(self._selected) if s]

    def selected_count(self) -> int:
        return sum(self._selected)

    def selected_records(self, records: "list[dict]") -> "list[dict]":
        """선택된 인덱스의 레코드만, 원본 순서대로."""
        return [records[i] for i in self.selected_indices()]
