"""전-선언 큐 상태 모델 — Qt·웹 비의존 순수 파이썬(R-flow 블록 3, 결정 16·18).

txt 기안 세션의 데이터 존 선택은 **전-선언**이다(결정 16): 행 클릭은 복사 선언이 아니라
"복사용 렌더링 큐를 만들라"는 선언이다. 커서가 목록을 걷지 않고 **큐가 한 장 카드(고정
작업점)를 지나간다** — 편입 순서 보존 + 멱등 재복사·완주=미처리 소진 + 작업점 = 항상 첫
미처리("포커스=첫 미답 질문"의 큐 판, 블록 1 승계).

## 계약

- **레코드 정체 = 데이터소스 세션 내 인덱스**(:class:`~hwpxfiller.gui.selection_state.
  SelectionModel` 과 같은 키). 선택은 이 모델의 진입점이고, 복사 상태(미처리/처리)는 그 위의
  집합 구분이다. 선택·큐는 세션 휘발이라(결정 8) 데이터 교체 시 컨트롤러가 새로 만든다.
- **표시 순서는 고정이다**(U2 §2.15, #338): :meth:`display_order` 는 편입(선언) 순서의 고정
  사본이고 복사는 그 순서를 **바꾸지 않는다** — 점 띠의 자리는 그대로이고 색(상태)만 바뀐다.
  종전의 「미처리 다음 처리 후미」 순회는 한 화면에 순서 둘(고정 `position` vs 큐 띠)을
  낳아 화해 주석으로 봉합해야 했다(2R P1). `_copied_order` 는 복사 상태의 단일 출처(멤버십
  = ``is_copied``, 순서 = 복사순 ``copied_tail``)로 남고 **순서 지배만 잃는다**.
- **처리 상태는 선택에 종속**(``copied ⊆ selected``): 행을 해제하면 큐에서 완전히 빠지고
  (복사 이력 포함), 다시 선택하면 새 미처리로 돌아온다 — 오클릭 토글이 자가복구하는
  블록 4 결정 26 문법과 정합. :meth:`reconcile` 을 선택 변경 후 호출해 큐를 재봉합한다.
- **미루기 사망**(R-info 3부 결정 10 — R-flow 결정 19 회수, #148 슬라이스 3c). 막힌 카드의
  탈출구는 이제 **자유 이동**(◀▶ :meth:`step` · 색인 점 클릭 :meth:`set_current`)이라
  큐 뒤로 보내는 동사가 필요 없다. ``reconcile`` 이 유지하는 표시 순서가 담보하는 것은
  **선택 편입 순서**(선언 순서) 하나다.
- **복사**(결정 16): 대상을 처리 상태로 옮기고 멱등 재복사를 허용한다. 작업점은 복사한
  카드에 머문다 — "넘어가기"(다음 미처리로의 전진)가 사용자의 사실상 붙여넣기 서명이라
  자동 전진은 명시 opt-in(표면 소관, 결정 16). 전진 대상은 **표시 순서상 가장 이른
  미처리**(:meth:`advance_to_next_uncopied`)다.
- **레코드 비소유**: 이 모델은 인덱스만 다룬다 — 빈칸 게이트 술어(카드에 빈 값이 있나)는
  레코드를 아는 컨트롤러가 :func:`~hwpxfiller.domain.text_render.render_segments` 로 판정한다.

회귀 = ``tests/test_txt_queue.py``. 표면 배선(데이터 존 테이블·작업점 카드·상태 색인)은 PR-2·3.
"""
from __future__ import annotations

from .selection_state import SelectionModel


class TxtQueueModel:
    """선택(전-선언) → 고정 표시 순서 + 처리 집합 + 고정 작업점(current). 뷰는 이 API 만 호출한다."""

    def __init__(self, selection: SelectionModel) -> None:
        self._sel = selection
        # 표시 순서의 단일 출처(편입순 고정 사본, #338) — 복사가 이 목록을 재배열하지 않는다.
        self._display_order: "list[int]" = []
        # 처리 집합(복사순) — 복사 상태의 단일 출처. ``is_copied`` 는 이 목록 멤버십이다
        # (별도 set 을 손으로 동기하지 않는다 — 두 구조가 어긋나는 결함류의 구조적 제거).
        # 미처리 목록도 따로 두지 않는다: ``uncopied`` = 표시 순서 − 이 멤버십(파생).
        self._copied_order: "list[int]" = []
        self._current: "int | None" = None
        self.reconcile()

    # ------------------------------------------------------------- 재봉합(선택 종속)
    def reconcile(self) -> None:
        """선택 지형에 큐를 맞춘다 — 해제분 제거·신규 선택분 표시 후미 추가·작업점 정규화.

        기존 표시 순서는 보존한다: 선택 변경은 지형만 바꾸고 순서를 갈아엎지 않는다.
        미루기 사망(결정 10) + 복사 후미 이동 사망(#338) 뒤 이 보존이 담보하는 것은
        **선택 편입 순서**(선언 순서) 하나다. 복사 상태는 선택에 종속(``copied ⊆ selected``)
        이라 해제된 행은 복사 이력까지 빠진다(재선택 시 새 미처리·표시 후미).

        **신규 편입 순서 = 인덱스 순**(reconcile 호출 단위): :class:`SelectionModel` 은
        클릭 순서를 모르는 bool 배열이라 한 번에 여러 개가 편입되면(범위 선택) 인덱스 순으로
        후미에 붙는다. 컨트롤러가 사용자 동작마다 reconcile 하면 동작 순서가 보존된다 —
        즉 순서 담보는 reconcile 입도까지이고, 시안 rebuild(ROWS 순)와도 정합.
        """
        sel_set = set(self._sel.selected_indices())
        self._copied_order = [i for i in self._copied_order if i in sel_set]
        self._display_order = [i for i in self._display_order if i in sel_set]
        tracked = set(self._display_order)
        for i in self._sel.selected_indices():  # 신규 편입분을 인덱스 순으로 표시 후미에 추가
            if i not in tracked:
                self._display_order.append(i)
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
        """미처리 목록(표시 순서) — 표시 순서에서 처리 멤버십을 뺀 파생값."""
        copied = set(self._copied_order)
        return [i for i in self._display_order if i not in copied]

    def copied_tail(self) -> "list[int]":
        """처리 집합(복사순) — 표시 순서가 아니라 「무엇을 어떤 순서로 복사했나」의 기록."""
        return list(self._copied_order)

    def display_order(self) -> "list[int]":
        """색인·순회 순서 = **편입순 고정 사본**(#338) — 복사해도 재배열되지 않는다."""
        return list(self._display_order)

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
        return self.selected_count() > 0 and not self.uncopied()

    # (``position_of`` 는 #338 에서 사망 — 미처리 큐 1-기반 순번의 소비자가 0이었다.
    #  사람이 읽는 자리는 고정 표시 서수 하나다: 표면은 ``display_order`` 의 index 를 쓴다.)

    # ------------------------------------------------------------- 변경(동사)
    def set_current(self, index: "int | None") -> None:
        """작업점 직접 지정(색인 점 클릭) — 큐 밖 인덱스는 무시(정규화가 되돌린다)."""
        if index is None or index in self._display_order:
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
        """대상(기본=작업점)을 처리 상태로 — 멱등. 표시 자리는 **불변**(색만 바뀐다, #338).

        반환 = 이번이 재복사인가(``True``=이미 복사됐던 것). **작업점은 건드리지 않는다** —
        전진은 표면의 opt-in(:meth:`advance_to_next_uncopied`). 처리 기록(`_copied_order`)
        안에서만 복사순 후미로 재정렬한다(멱등 재복사의 「최근 복사」 기록). 대상이 선택 밖·
        범위 밖이면 무시(선택=큐 편성의 전제, confirm-or-alarm: 크래시 아닌 무동작 False).
        """
        i = self._current if index is None else index
        if i is None or not (0 <= i < len(self._sel)) or not self._sel.is_selected(i):
            return False
        was = i in self._copied_order
        if was:
            self._copied_order.remove(i)
        self._copied_order.append(i)
        self._normalize_current()  # 작업점·표시 순서 모두 그대로 — 상태(색)만 바뀌었다
        return was

    def advance_to_next_uncopied(self) -> None:
        """다음 미처리로 전진(복사=전진 opt-in·↓ 서명) — 표시 순서상 가장 이른 미처리.
        없으면 현 위치 유지."""
        uncopied = self.uncopied()
        if uncopied:
            self._current = uncopied[0]
