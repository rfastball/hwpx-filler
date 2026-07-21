"""전-선언 큐 모델 단위 가드 — ``hwpxfiller.gui.txt_queue`` (R-flow 블록 3 결정 16·18).

큐는 선택(전-선언)에 종속한다: 편입(선언) 순서 보존 + 처리 후미 이동(멱등 재복사·완주) +
작업점=첫 미처리. 미루기는 R-info 3부 결정 10 에서 사망했다(#148 슬라이스 3c) — 자유 이동
(◀▶·점 클릭)이 대체하므로 큐 뒤로 보내는 동사가 없다. 순서 보존이 남아 담보하는 것은
**선택 편입 순서** 하나다(``test_new_selection_preserves_reconcile_order``).
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


def test_copy_moves_to_tail_current_stays_on_card():
    sel, q = make(3)
    was = q.copy()  # 작업점(0) 복사
    assert was is False
    assert q.is_copied(0)
    assert q.uncopied() == [1, 2]
    assert q.copied_tail() == [0]
    assert q.display_order() == [1, 2, 0]
    assert q.current == 0  # 넘어가기는 사용자 서명 — 자동 전진 안 함


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


def test_recopy_is_idempotent_and_reorders_tail():
    sel, q = make(3)
    q.copy(0)
    q.copy(1)
    assert q.copied_tail() == [0, 1]
    was = q.copy(0)  # 재복사
    assert was is True
    assert q.copied_tail() == [1, 0]  # 최근 복사가 후미로
    assert q.copied_count() == 2


def test_advance_to_next_uncopied_is_opt_in():
    sel, q = make(3)
    q.copy(0)
    assert q.current == 0
    q.advance_to_next_uncopied()  # 복사=전진 opt-in
    assert q.current == 1


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


def test_deselect_drops_from_queue_including_copy_history():
    sel, q = make(3)
    q.copy(0)
    assert q.is_copied(0)
    sel.toggle(0, False)  # 0 해제
    q.reconcile()
    assert not q.is_copied(0)  # 복사 이력까지 빠짐(copied ⊆ selected)
    assert 0 not in q.display_order()
    sel.toggle(0, True)  # 재선택 = 새 미처리(후미)
    q.reconcile()
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
    assert q.display_order() == [0, 1]  # 순회는 처리 후미로 계속 가능(멱등 재복사)


def test_position_of_reports_one_based_uncopied_rank():
    sel, q = make(3)
    assert q.position_of(0) == 1
    assert q.position_of(2) == 3
    q.copy(0)
    assert q.position_of(0) is None  # 처리분은 미처리 순번 없음
    assert q.position_of(1) == 1  # 앞이 빠지면 당겨진다


def test_copy_ignores_unselected_target():
    sel, q = make(2, all_selected=False)
    sel.toggle(0, True)
    q.reconcile()
    assert q.copy(1) is False  # 선택 안 된 1 은 복사 대상 아님
    assert q.copied_tail() == []
