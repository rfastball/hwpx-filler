"""전-선언 큐 상태 모델 — Qt·웹 비의존 순수 파이썬(R-flow 블록 3, 결정 16·18·19).

txt 기안 세션의 데이터 존 선택은 **전-선언**이다(결정 16): 행 클릭은 복사 선언이 아니라
"복사용 렌더링 큐를 만들라"는 선언이다. 커서가 목록을 걷지 않고 **큐가 한 장 카드(고정
작업점)를 지나간다** — 미처리 순서 보존 + 처리분 후미 이동(멱등 재복사·완주=미처리 소진) +
작업점 = 항상 첫 미처리("포커스=첫 미답 질문"의 큐 판, 블록 1 승계).

## 계약

- **레코드 정체 = 데이터소스 세션 내 인덱스**(:class:`~hwpxfiller.gui.selection_state.
  SelectionModel` 과 같은 키). 선택은 이 모델의 진입점이고, 큐는 선택∩미복사(미처리)와
  처리 후미(복사순)로 갈린다. 선택·큐는 세션 휘발이라(결정 8) 데이터 교체 시 컨트롤러가
  새로 만든다.
- **처리 상태는 선택에 종속**(``copied ⊆ selected``): 행을 해제하면 큐에서 완전히 빠지고
  (복사 이력 포함), 다시 선택하면 새 미처리로 돌아온다 — 오클릭 토글이 자가복구하는
  블록 4 결정 26 문법과 정합. :meth:`reconcile` 을 선택 변경 후 호출해 큐를 재봉합한다.
- **미루기**(결정 19): 막힌 미처리 카드를 큐 뒤로 보내는 유일한 탈출구. 처리분은 못 미룬다
  (이미 후미). 미루기 순서는 명시 보존한다 — ``reconcile`` 은 선택 지형만 조정하고 기존
  미처리 순서를 유지한다(시안 데모가 매 렌더 rebuild 로 미루기를 지웠던 결함의 교정).
- **복사**(결정 16): 대상을 처리 후미로 옮기고 멱등 재복사를 허용한다. 작업점은 복사한
  카드에 머문다 — "넘어가기"(다음 미처리로의 전진)가 사용자의 사실상 붙여넣기 서명이라
  자동 전진은 명시 opt-in(표면 소관, 결정 16).
- **레코드 비소유**: 이 모델은 인덱스만 다룬다 — 빈칸 게이트 술어(카드에 빈 값이 있나)는
  레코드를 아는 컨트롤러가 :func:`~hwpxfiller.core.text_render.render_segments` 로 판정한다.

회귀 = ``tests/test_txt_queue.py``. 표면 배선(데이터 존 테이블·작업점 카드·상태 색인)은 PR-2·3.
"""
from __future__ import annotations

from .selection_state import SelectionModel


class TxtQueueModel:
    """선택(전-선언) → 미처리 큐 + 처리 후미 + 고정 작업점(current). 뷰는 이 API 만 호출한다."""

    def __init__(self, selection: SelectionModel) -> None:
        self._sel = selection
        # 처리 후미(복사순) — 복사 상태의 단일 출처. ``is_copied`` 는 이 목록 멤버십이다
        # (별도 set 을 손으로 동기하지 않는다 — 두 구조가 어긋나는 결함류의 구조적 제거).
        self._copied_order: "list[int]" = []
        self._uncopied_order: "list[int]" = []      # 미처리 큐(순서=편입순 + 미루기 반영)
        self._current: "int | None" = None
        self.reconcile()

    # ------------------------------------------------------------- 재봉합(선택 종속)
    def reconcile(self) -> None:
        """선택 지형에 큐를 맞춘다 — 해제분 제거·신규 선택분 미처리 후미 추가·작업점 정규화.

        기존 미처리 순서(미루기 포함)는 보존한다: 선택 변경은 지형만 바꾸고 순서를
        갈아엎지 않는다. 복사 상태는 선택에 종속(``copied ⊆ selected``)이라 해제된 행은
        복사 이력까지 빠진다(재선택 시 새 미처리).

        **신규 편입 순서 = 인덱스 순**(reconcile 호출 단위): :class:`SelectionModel` 은
        클릭 순서를 모르는 bool 배열이라 한 번에 여러 개가 편입되면(범위 선택) 인덱스 순으로
        후미에 붙는다. 컨트롤러가 사용자 동작마다 reconcile 하면 동작 순서가 보존된다 —
        즉 순서 담보는 reconcile 입도까지이고, 시안 rebuild(ROWS 순)와도 정합.
        """
        sel_set = set(self._sel.selected_indices())
        self._copied_order = [i for i in self._copied_order if i in sel_set]
        copied_set = set(self._copied_order)
        self._uncopied_order = [
            i for i in self._uncopied_order if i in sel_set and i not in copied_set
        ]
        tracked = set(self._uncopied_order) | copied_set
        for i in self._sel.selected_indices():  # 신규 편입분을 인덱스 순으로 미처리 후미에 추가
            if i not in tracked:
                self._uncopied_order.append(i)
        self._normalize_current()

    def _normalize_current(self) -> None:
        """작업점 = 큐 안의 유효 지점. 비었으면 None, 유효 밖이면 첫 미처리(없으면 첫 표시)."""
        order = self.display_order()
        if not order:
            self._current = None
        elif self._current is None or self._current not in order:
            uncopied = self.uncopied()
            self._current = uncopied[0] if uncopied else order[0]

    # ------------------------------------------------------------- 조회(정체)
    def uncopied(self) -> "list[int]":
        """미처리 큐(순서 보존)."""
        return list(self._uncopied_order)

    def copied_tail(self) -> "list[int]":
        """처리 후미(복사순)."""
        return list(self._copied_order)

    def display_order(self) -> "list[int]":
        """색인·순회 순서 = 미처리 다음 처리 후미(시안 dispIds 동형)."""
        return self._uncopied_order + self._copied_order

    def is_copied(self, index: int) -> bool:
        return index in self._copied_order

    @property
    def current(self) -> "int | None":
        return self._current

    def selected_count(self) -> int:
        """전-선언 큐 규모(선택 수) — 슬롯 총계."""
        return self._sel.selected_count()

    def copied_count(self) -> int:
        return len(self._copied_order)

    def is_complete(self) -> bool:
        """완주 = 큐가 비지 않았고 미처리 0(완주=조용한 한 줄의 판정, 결정 16)."""
        return self.selected_count() > 0 and not self._uncopied_order

    def position_of(self, index: int) -> "int | None":
        """미처리 큐에서의 1-기반 순번(없으면 None) — 슬롯 재진술용."""
        if index in self._uncopied_order:
            return self._uncopied_order.index(index) + 1
        return None

    # ------------------------------------------------------------- 변경(동사)
    def set_current(self, index: "int | None") -> None:
        """작업점 직접 지정(색인 점 클릭) — 큐 밖 인덱스는 무시(정규화가 되돌린다)."""
        if index is None or index in self.display_order():
            self._current = index
        self._normalize_current()

    def step(self, delta: int) -> None:
        """작업점을 표시 순서로 이동(↓/↑) — 경계에서 멈춘다(순환 안 함)."""
        order = self.display_order()
        if not order:
            return
        if self._current is None or self._current not in order:
            self._normalize_current()
            return
        i = order.index(self._current)
        self._current = order[max(0, min(len(order) - 1, i + delta))]

    def copy(self, index: "int | None" = None) -> bool:
        """대상(기본=작업점)을 처리 후미로 — 멱등. 이미 복사분이면 후미 재정렬만.

        반환 = 이번이 재복사인가(``True``=이미 복사됐던 것). **작업점은 건드리지 않는다** —
        작업점 카드를 복사하면 그 카드는 후미로 가되 작업점은 여전히 그 카드를 가리키고(머묾),
        비작업점 카드를 명시 복사하면 작업점은 있던 자리에 그대로 있다(조용한 작업점 이동
        금지). 전진은 표면의 opt-in(:meth:`advance_to_next_uncopied`). 대상이 선택 밖·범위
        밖이면 무시(선택=큐 편성의 전제, confirm-or-alarm: 크래시 아닌 무동작 False)."""
        i = self._current if index is None else index
        if i is None or not (0 <= i < len(self._sel)) or not self._sel.is_selected(i):
            return False
        was = i in self._copied_order
        if i in self._uncopied_order:
            self._uncopied_order.remove(i)
        if i in self._copied_order:
            self._copied_order.remove(i)
        self._copied_order.append(i)
        self._normalize_current()  # 작업점이 여전히 유효(후미로 간 카드 포함) — 이동시키지 않음
        return was

    def advance_to_next_uncopied(self) -> None:
        """다음 미처리로 전진(복사=전진 opt-in·↓ 서명) — 없으면 현 위치 유지."""
        if self._uncopied_order:
            self._current = self._uncopied_order[0]

    def defer(self, index: "int | None" = None) -> None:
        """미처리 카드를 큐 뒤로(결정 19) — 처리분·큐 밖은 무시.

        **작업점 이동은 미룬 카드가 작업점일 때만**: 작업점을 미루면 같은 자리(빈 슬롯)의
        다음 미처리로 넘어간다(막힌 카드에서 계속 걷는 탈출구). 비작업점 카드를 미루면
        (건별 미루기 버튼) 작업점은 있던 카드에 그대로 있다 — 조용한 작업점 이동 금지."""
        i = self._current if index is None else index
        if i is None or i in self._copied_order or i not in self._uncopied_order:
            return
        was_current = i == self._current
        pos = self._uncopied_order.index(i)
        self._uncopied_order.remove(i)
        self._uncopied_order.append(i)
        if was_current:
            uncopied = self._uncopied_order
            self._current = uncopied[min(pos, len(uncopied) - 1)] if uncopied else None
