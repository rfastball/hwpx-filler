"""V13 공용 패턴 스윕 가드 — offscreen.

공용 헬퍼(view_helpers)와 그 이식 표면을 검증한다:
- UD-11: 카드 액션 버튼 세로 압착 방지 — item sizeHint 가 카드 필요 높이를 수용(기하 단언).
- UD-17: 빈 상태 패턴 이식 — 목록 0건이면 스택이 빈 상태 페이지로 교체.
- UD-26: 빈 값/결측 명시 재진술 — 표 셀·미리보기 문자열이 무표시 공백으로 두지 않음.
- UD-30: 가변 길이 문자열 말줄임+툴팁 — 좁은 폭에서 말줄임하고 전체 이름을 툴팁으로.

깊은 로직은 각 패널/상태 테스트가 헤드리스로 본다. 여기선 공용 규율의 이식만 확인한다.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from hwpxfiller.core.dataset_pool import (  # noqa: E402
    DatasetPoolItem,
    DatasetPoolRegistry,
)
from hwpxfiller.core.job import JobRegistry  # noqa: E402
from hwpxfiller.core.mapping import FieldMapping, MappingProfile  # noqa: E402
from hwpxfiller.core.mapping_base import MappingBaseRegistry  # noqa: E402
from hwpxfiller.gui.view_helpers import (  # noqa: E402
    EMPTY_VALUE_MARKER,
    MISSING_VALUE_MARKER,
    ElidedLabel,
    restate_preview_item,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ------------------------------------------------------------ UD-11 기하 단언
def _assert_cards_not_compressed(list_widget) -> int:
    """각 카드의 item 배정 높이가 카드·액션 버튼 필요 높이를 수용하는지 단언(UD-11).

    미폴리시 시점 sizeHint 박제가 되살아나면(재동기 미이식) item 높이가 폴리시 후 카드
    높이보다 작아져 버튼이 압착된다 — 그 회귀를 기하로 잡는다. 반환: 검사한 카드 수.
    """
    checked = 0
    for i in range(list_widget.count()):
        it = list_widget.item(i)
        card = list_widget.itemWidget(it)
        if card is None:
            continue
        card.ensurePolished()
        buttons = card.findChildren(QPushButton)
        assert buttons, "카드에 액션 버튼이 없습니다"
        need = max(b.sizeHint().height() for b in buttons)
        assert need >= 20, f"버튼 sizeHint 높이가 비정상적으로 낮습니다: {need}px"
        # 카드 자체가 버튼을 수용해야 하고, item 배정 높이가 카드 높이를 수용해야 한다.
        assert card.sizeHint().height() >= need
        assert it.sizeHint().height() >= card.sizeHint().height(), (
            f"item 높이({it.sizeHint().height()})가 카드 필요 높이"
            f"({card.sizeHint().height()})보다 작습니다 — 액션 버튼 세로 압착(UD-11)"
        )
        checked += 1
    return checked


def test_pool_card_action_buttons_not_vertically_compressed(qapp, tmp_path):
    """데이터 풀 3버튼 카드(보관/은퇴/삭제)가 압착되지 않는다(UD-11)."""
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="활성D", kind="excel", opts={"path": "/a.xlsx"}))
    reg.save(DatasetPoolItem(name="둘째D", kind="excel", opts={"path": "/b.xlsx"}))
    panel = DatasetPoolPanel(reg)
    panel._sync_cards()  # 폴리시 후 재동기(생성자도 부르지만 명시적으로 확정)
    assert _assert_cards_not_compressed(panel.list) == 2


def test_vocab_cards_not_compressed(qapp, tmp_path):
    """매핑 프로파일 카드도 같은 공용 재동기로 압착되지 않는다(UD-11)."""
    from hwpxfiller.gui.vocab_workbench import VocabWorkbenchPanel

    breg = MappingBaseRegistry(tmp_path / "bases")
    breg.save(MappingProfile(name="공고베이스", mappings=[
        FieldMapping(template_field="계약명", sources=["bidNtceNm"]),
    ]))
    vw = VocabWorkbenchPanel(breg)
    vw._sync_cards()
    assert _assert_cards_not_compressed(vw.list) == 1


# ------------------------------------------------------------ UD-17 빈 상태
def test_empty_states_swap_stack_on_zero(qapp, tmp_path):
    """풀·프로파일·매트릭스·홈 txt 목록이 0건이면 빈 상태 페이지(index 1)로 교체(UD-17)."""
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel
    from hwpxfiller.gui.home import JobListHome
    from hwpxfiller.gui.matrix_view import MatrixRunView
    from hwpxfiller.gui.vocab_workbench import VocabWorkbenchPanel

    pool = DatasetPoolPanel(DatasetPoolRegistry(tmp_path / "pool"))
    assert pool.stack.currentIndex() == 1
    vw = VocabWorkbenchPanel(MappingBaseRegistry(tmp_path / "bases"))
    assert vw.stack.currentIndex() == 1
    mv = MatrixRunView(JobRegistry(tmp_path / "jobs"))
    assert mv.job_stack.currentIndex() == 1
    home = JobListHome(JobRegistry(tmp_path / "jobs2"))
    assert home.txt_stack.currentIndex() == 1  # 즉시 기안 목록 빈 상태
    assert home.btn_txt_empty_new is not None    # 빈 상태 CTA(＋ 새 기안)


def test_pool_empty_state_swaps_back_when_populated(qapp, tmp_path):
    """등록되면 목록 페이지(index 0)로 돌아온다 — 빈 상태가 붙박이가 아니다(UD-17)."""
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    reg = DatasetPoolRegistry(tmp_path)
    panel = DatasetPoolPanel(reg)
    assert panel.stack.currentIndex() == 1
    reg.save(DatasetPoolItem(name="X", kind="excel", opts={"path": "/a.xlsx"}))
    panel.refresh()
    assert panel.stack.currentIndex() == 0
    assert panel.list.count() == 1


# ------------------------------------------------------------ UD-26 빈 값 재진술
def test_restate_preview_item_marks_empty_and_missing(qapp):
    """표 셀이 빈 값·결측을 무표시 공백이 아니라 마커로 재진술한다(UD-26)."""
    assert restate_preview_item({"a": ""}, "a").text() == EMPTY_VALUE_MARKER
    assert restate_preview_item({"a": "   "}, "a").text() == EMPTY_VALUE_MARKER
    assert restate_preview_item({}, "a").text() == MISSING_VALUE_MARKER  # 키 부재(left 조인)
    assert restate_preview_item({"a": "값"}, "a").text() == "값"


def test_txt_preview_restates_blank_positions(qapp):
    """txt 미리보기가 빈 값 위치를 마커로 남긴다 — 무표시 소멸 방지(UD-26 E7)."""
    from hwpxfiller.gui.txt_view import TxtDraftView

    html = TxtDraftView._build_preview_html(
        "담당: {{담당}} / 금액: {{금액}} / 미상: {{미상}}",
        {"담당": "", "금액": "100"},
    )
    assert "〈빈 값〉" in html          # blank 위치 재진술
    assert "{{미상}}" in html           # missing 은 빨간 토큰 그대로(ADR-E)
    assert "100" in html                # fill 은 값 그대로


def test_template_preview_result_marks_empty_value(qapp, tmp_path):
    """FILLED 미리보기 문구가 빈 값 필드를 '(비움)'으로 재진술한다(UD-26 F5)."""
    from hwpxfiller.gui.template_manager_state import TemplateManagerViewModel

    vm = TemplateManagerViewModel(tmp_path)
    line = vm.format_preview_result("x.hwpx", {"계약명": "", "금액": "100"})
    assert "계약명 = (비움)" in str(line)
    assert "금액 = 100" in str(line)


# ------------------------------------------------------------ UD-30 말줄임+툴팁
def test_elided_label_elides_and_sets_tooltip_when_narrow(qapp):
    """좁은 폭에서 말줄임하고 전체 문자열을 툴팁으로, 넓으면 원문·툴팁 해제(UD-30)."""
    full = "아주" * 40
    lbl = ElidedLabel(full, max_width=200)
    lbl.resize(60, 20)
    assert lbl.text() != full           # 말줄임됨
    assert lbl.toolTip() == full        # 전체 이름 툴팁
    assert lbl.full_text() == full
    lbl.resize(4000, 20)
    lbl._relayout()
    assert lbl.text() == full           # 넓으면 원문
    assert lbl.toolTip() == ""          # 잘리지 않으면 툴팁 없음


def test_elided_label_sizehint_capped_by_max_width(qapp):
    """max_width 가 sizeHint 폭을 눌러 긴 문자열이 형제(상태 배지)를 밀어내지 않는다(UD-30)."""
    lbl = ElidedLabel("가" * 200, max_width=180)
    assert lbl.sizeHint().width() <= 180
