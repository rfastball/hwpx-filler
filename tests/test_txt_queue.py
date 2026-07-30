"""전-선언 큐 모델 단위 가드 — ``hwpxfiller.gui.txt_queue`` (R-flow 블록 3 결정 16·18).

큐는 선택(전-선언)에 종속한다: 편입(선언) 순서 보존 + 멱등 재복사·완주 + 작업점=첫 미처리.
미루기는 R-info 3부 결정 10 에서 사망했다(#148 슬라이스 3c) — 자유 이동(◀▶·점 클릭)이
대체하므로 큐 뒤로 보내는 동사가 없다. **복사의 표시 후미 이동도 U2 §2.15(#338)에서
사망했다**: 표시 순서는 편입순 고정 사본이고 복사는 상태(색)만 바꾼다 — 한 화면에 순서
둘(고정 자리 vs 큐 띠)을 두면 그중 하나는 반드시 거짓이 되기 때문이다. 순서 보존이 담보하는
것은 **선택 편입 순서** 하나다(``test_new_selection_preserves_reconcile_order``).
"""
from __future__ import annotations

from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.txt_queue import TxtQueueModel


def make(count: int, all_selected: bool = True) -> "tuple[SelectionModel, TxtQueueModel]":
    sel = SelectionModel(count, all_selected=all_selected)
    return sel, TxtQueueModel(sel)


def test_empty_selection_has_no_queue_or_current():
    sel, q = make(3, all_selected=False)
    assert q.uncopied() == []
    assert q.display_order() == []
    assert q.current is None
    assert not q.is_complete()


def test_all_selected_queues_in_order_current_first():
    sel, q = make(3)
    assert q.uncopied() == [0, 1, 2]
    assert q.current == 0  # 작업점 = 첫 미처리
    assert q.selected_count() == 3


def test_copy_changes_state_but_never_the_display_order():
    """#338 회귀 그물 — 복사 뒤 ``display_order()`` 불변(자리는 그대로, 색만 바뀐다)."""
    sel, q = make(3)
    was = q.copy()  # 작업점(0) 복사
    assert was is False
    assert q.is_copied(0)
    assert q.uncopied() == [1, 2]
    assert q.copied_tail() == [0]
    assert q.display_order() == [0, 1, 2]  # 표시 순서 고정 — 후미 이동 없음(#338)
    assert q.current == 0  # 넘어가기는 사용자 서명 — 자동 전진 안 함
    q.copy(2)              # 중간 건너뛴 복사도 자리를 흔들지 않는다
    assert q.display_order() == [0, 1, 2]
    assert q.uncopied() == [1]


def test_copy_non_current_index_leaves_work_point():
    """비작업점 카드를 명시 복사해도 작업점은 있던 자리에 머문다(조용한 이동 금지)."""
    sel, q = make(3)
    assert q.current == 0
    q.copy(2)  # 작업점 아님(0)인데 2 를 복사
    assert q.is_copied(2)
    assert q.current == 0  # 작업점 불변


def test_copy_out_of_range_returns_false_no_crash():
    """범위 밖 인덱스는 IndexError 대신 무동작 False(confirm-or-alarm: 크래시 아님)."""
    sel, q = make(2)
    assert q.copy(5) is False  # 레코드 수 초과 — 조용한 무동작
    assert q.copied_tail() == []


def test_recopy_is_idempotent_and_reorders_only_the_copy_record():
    """재복사는 멱등 — 「최근 복사」 기록(copied_tail)만 재정렬되고 표시 순서는 불변."""
    sel, q = make(3)
    q.copy(0)
    q.copy(1)
    assert q.copied_tail() == [0, 1]
    was = q.copy(0)  # 재복사
    assert was is True
    assert q.copied_tail() == [1, 0]  # 최근 복사가 기록 후미로
    assert q.copied_count() == 2
    assert q.display_order() == [0, 1, 2]  # 기록이 움직여도 자리는 그대로(#338)


def test_advance_to_next_uncopied_is_opt_in():
    sel, q = make(3)
    q.copy(0)
    assert q.current == 0
    q.advance_to_next_uncopied()  # 복사=전진 opt-in
    assert q.current == 1


def test_advance_goes_to_the_earliest_uncopied_in_display_order():
    """전진 규칙 현행 유지(#338) — 5번을 복사해도 미처리 2번이 남아 있으면 2번으로 간다."""
    sel, q = make(5)
    q.copy(0)
    q.copy(1)
    q.copy(3)
    q.set_current(4)
    q.copy(4)                     # 후미 카드 복사 — 미처리는 2 하나
    q.advance_to_next_uncopied()
    assert q.current == 2
    q.copy(2)                     # 미처리 0 — 전진할 곳이 없으면 머문다
    q.advance_to_next_uncopied()
    assert q.current == 2


def test_step_walks_display_order_and_clamps():
    sel, q = make(3)
    q.step(1)
    assert q.current == 1
    q.step(1)
    assert q.current == 2
    q.step(1)
    assert q.current == 2  # 경계에서 멈춤(순환 안 함)
    q.step(-5)
    assert q.current == 0


def test_step_bounds_are_fixed_even_after_copying():
    """#338 — 복사 뒤에도 ‹ › 는 고정 자리 기준이다: 첫 카드를 복사해도 「이전」이 생기지 않는다."""
    sel, q = make(3)
    q.copy(0)              # 종전엔 0 이 후미로 가 순회상 마지막이 됐다
    q.step(-1)
    assert q.current == 0  # 고정 순서의 머리 — 뒤로 갈 곳이 없다
    q.step(1)
    assert q.current == 1  # 다음 = 고정 순서의 1


def test_set_current_ignores_out_of_queue():
    sel, q = make(2, all_selected=False)
    sel.toggle(1, True)
    q.reconcile()
    q.set_current(0)  # 0 은 선택 안 됨 → 무시
    assert q.current == 1


def test_defer_verb_is_dead():
    """미루기 사망(결정 10 · 슬라이스 3c) — 큐 뒤로 보내는 동사가 모델에 없다.

    막힌 카드의 탈출구는 자유 이동(:meth:`step`·:meth:`set_current`)이라 ``defer`` 는
    회수됐다. 되살아나면(재유입) 「미루기 순서 명시 보존」 계약도 함께 부활해야 하므로
    부재를 못박는다.
    """
    _sel, q = make(3)
    assert not hasattr(q, "defer")


def test_position_of_verb_is_dead():
    """``position_of`` 사망(#338) — 미처리 큐 1-기반 순번의 소비자가 0이었다.

    사람이 읽는 자리는 고정 표시 서수 하나다(부제 「선택 당시 표시순서로 고정된 항목」).
    되살아나면 한 화면에 번호 축이 둘이 되므로 부재를 못박는다.
    """
    _sel, q = make(3)
    assert not hasattr(q, "position_of")


def test_deselect_drops_from_queue_including_copy_history():
    sel, q = make(3)
    q.copy(0)
    assert q.is_copied(0)
    sel.toggle(0, False)  # 0 해제
    q.reconcile()
    assert not q.is_copied(0)  # 복사 이력까지 빠짐(copied ⊆ selected)
    assert 0 not in q.display_order()
    sel.toggle(0, True)  # 재선택 = 새 미처리(표시 후미)
    q.reconcile()
    assert q.display_order() == [1, 2, 0]  # 재편입은 새 선언 — 표시 후미에 붙는다
    assert 0 in q.uncopied()
    assert not q.is_copied(0)


def test_new_selection_preserves_reconcile_order():
    """동작마다 reconcile 하면 편입(동작) 순서가 보존된다 — 1 먼저, 0 나중 → [1, 0]."""
    sel, q = make(3, all_selected=False)
    sel.toggle(1, True)
    q.reconcile()
    sel.toggle(0, True)
    q.reconcile()
    assert q.uncopied() == [1, 0]
    assert q.display_order() == [1, 0]


def test_batched_selection_joins_in_index_order():
    """한 reconcile 에 여러 개가 편입되면(범위 선택) 인덱스 순 — SelectionModel 은 클릭 순서 모름."""
    sel, q = make(3, all_selected=False)
    sel.toggle(2, True)
    sel.toggle(0, True)  # reconcile 전에 배치 선택(2 먼저 클릭했어도)
    q.reconcile()
    assert q.uncopied() == [0, 2]  # 인덱스 순(순서 담보는 reconcile 입도까지)


def test_completion_when_all_uncopied_drained():
    sel, q = make(2)
    assert not q.is_complete()
    q.copy(0)
    assert not q.is_complete()
    q.copy(1)
    assert q.is_complete()  # 미처리 0 = 완주
    assert q.uncopied() == []
    assert q.display_order() == [0, 1]  # 순회는 고정 순서 그대로 계속 가능(멱등 재복사)


def test_copy_ignores_unselected_target():
    sel, q = make(2, all_selected=False)
    sel.toggle(0, True)
    q.reconcile()
    assert q.copy(1) is False  # 선택 안 된 1 은 복사 대상 아님
    assert q.copied_tail() == []
