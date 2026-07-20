"""전-선언 큐 모델 단위 가드 — ``hwpxfiller.gui.txt_queue`` (R-flow 블록 3 결정 16·18·19).

큐는 선택(전-선언)에 종속한다: 미처리 순서 보존 + 처리 후미 이동(멱등 재복사·완주) +
작업점=첫 미처리 + 미루기. 시안 데모(block3-verb-n-demo)가 매 렌더 rebuild 로 미루기를
지웠던 결함의 교정을 특히 가드한다.
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


def test_defer_moves_uncopied_to_tail_and_persists():
    """미루기는 미처리 큐 뒤로 보내고 그 순서가 유지된다(reconcile 이 지우지 않음)."""
    sel, q = make(3)
    q.defer(0)
    assert q.uncopied() == [1, 2, 0]
    assert q.current == 1  # 같은 자리의 다음
    q.reconcile()  # 선택 재봉합에도 미루기 순서 보존
    assert q.uncopied() == [1, 2, 0]


def test_defer_ignores_copied_and_out_of_queue():
    sel, q = make(2)
    q.copy(0)
    order_before = q.uncopied()
    q.defer(0)  # 처리분은 못 미룸
    assert q.uncopied() == order_before


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


def test_new_selection_appends_to_uncopied_tail():
    sel, q = make(3, all_selected=False)
    sel.toggle(1, True)
    q.reconcile()
    sel.toggle(0, True)
    q.reconcile()
    assert q.uncopied() == [1, 0]  # 선택 순서로 후미 추가(원본 인덱스 순 아님)


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
