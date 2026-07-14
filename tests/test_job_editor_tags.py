"""작업 에디터 분류 태그 저장 게이트 — 반쯤 채운 행·중복 축 차단, 발견 실패 강등 규율.

세 발견의 회귀 방어:
- #1 중복 축: tags() 가 뒤 값으로 앞 값을 조용히 덮는 대신 저장 전 시끄럽게 막는다.
- #4 반쯤 채운 행: 축·값 중 하나만 채운 행을 조용히 버리는 대신 막는다.
- #7 발견 예외 협소화: 예상 IO·파싱 실패만 조용히 빈 후보로, 프로그래밍 회귀는 전파.

로직(validate_tags)은 순수 문자열 술어라 가볍게 검증하고, 저장 게이트 배선만 위저드로
확인한다(test_gui_smoke.py 의 qapp 픽스처·offscreen 관례를 따른다).
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hwpxfiller.core.schema import FieldSpec, TemplateSchema  # noqa: E402
from hwpxfiller.data.nara import NaraStdDataSource  # noqa: E402
from hwpxfiller.gui.mapping_state import MappingModel  # noqa: E402

NARA_ALIASES = NaraStdDataSource.field_labels()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _complete_model() -> MappingModel:
    """공고명에 소스를 실어 확정한 완료 모델 — accept() 저장 게이트 전제 충족용."""
    schema = TemplateSchema(fields=[FieldSpec("공고명", "text", 1, False, "공 고 명:")])
    model = MappingModel.from_suggestions(schema, list(NARA_ALIASES), NARA_ALIASES)
    for i, row in enumerate(model.rows):
        if row.template_field == "공고명":
            model.set_source(i, "bidNtceNm")
    model.confirm_all()
    return model


# ---------------------------------------------------------- validate_tags(순수 술어)
def test_validate_tags_passes_clean_and_empty_rows(qapp, tmp_path):
    """축·값 둘 다 채운 행 + 완전 빈 행 혼재 = 통과("")—빈 행은 무해한 no-op(D12)."""
    from hwpxfiller.gui.job_editor import SaveJobPage

    page = SaveJobPage()
    page._add_tag_row("금액구간", "1억미만")
    page._add_tag_row("", "")  # 완전 빈 행 = 양성 no-op
    assert page.validate_tags() == ""
    assert page.tags() == {"금액구간": "1억미만"}


def test_validate_tags_blocks_half_filled_row_missing_axis(qapp):
    """#4 — 값만 있고 축이 빈 행은 차단(tags() 가 조용히 버리는 위험)."""
    from hwpxfiller.gui.job_editor import SaveJobPage

    page = SaveJobPage()
    page._add_tag_row("", "1억미만")  # 값만
    reason = page.validate_tags()
    assert reason  # 차단 사유 존재
    assert "분류 기준" in reason and "1억미만" in reason  # 어느 값이 문제인지 재진술


def test_validate_tags_blocks_half_filled_row_missing_value(qapp):
    """#4 반대 방향 — 축만 있고 값이 빈 행도 차단."""
    from hwpxfiller.gui.job_editor import SaveJobPage

    page = SaveJobPage()
    page._add_tag_row("금액구간", "")  # 축만
    reason = page.validate_tags()
    assert reason
    assert "값" in reason and "금액구간" in reason


def test_validate_tags_blocks_duplicate_axis(qapp):
    """#1 — 같은 축 두 행(다른 값)은 차단: tags() 가 앞 값을 조용히 덮어 소실시킨다."""
    from hwpxfiller.gui.job_editor import SaveJobPage

    page = SaveJobPage()
    page._add_tag_row("금액구간", "1억미만")
    page._add_tag_row("금액구간", "고시이상")  # 같은 축 중복
    reason = page.validate_tags()
    assert reason
    assert "금액구간" in reason and "중복" in reason
    # tags() 자체는 여전히 (게이트 통과 후 쓰이도록) 사전을 만든다 — 자동병합 아님.
    assert page.tags() == {"금액구간": "고시이상"}  # 뒤 값 승리(게이트가 막을 상태)


# ------------------------------------------------------- accept() 저장 게이트 배선
def test_accept_blocks_duplicate_axis_and_does_not_save(qapp, tmp_path, monkeypatch):
    """#1 — 중복 축이 있으면 accept 가 경고+차단, 조용한 덮어쓰기 저장이 없다."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg = JobRegistry(tmp_path)
    wiz = JobEditorWizard(reg)
    wiz.template_path = "/t.hwpx"
    wiz.model = _complete_model()
    wiz._save_page.ed_name.setText("중복축작업")
    wiz._save_page.ed_pattern.setText("공고-{{공고명}}")
    wiz._save_page._add_tag_row("금액구간", "1억미만")
    wiz._save_page._add_tag_row("금액구간", "고시이상")

    warned: "list[str]" = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    wiz.accept()
    assert warned and "금액구간" in warned[-1]  # 어느 축이 문제인지 고지
    assert not reg.exists("중복축작업")          # 조용한 저장 없음


def test_accept_blocks_half_filled_tag_row_and_does_not_save(qapp, tmp_path, monkeypatch):
    """#4 — 반쯤 채운 태그 행이 있으면 accept 가 경고+차단(사용자 입력 침묵 소실 방지)."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg = JobRegistry(tmp_path)
    wiz = JobEditorWizard(reg)
    wiz.template_path = "/t.hwpx"
    wiz.model = _complete_model()
    wiz._save_page.ed_name.setText("반쯤작업")
    wiz._save_page.ed_pattern.setText("공고-{{공고명}}")
    wiz._save_page._add_tag_row("금액구간", "")  # 축만 — 반쯤 채움

    warned: "list[str]" = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    wiz.accept()
    assert warned and "금액구간" in warned[-1]
    assert not reg.exists("반쯤작업")


def test_accept_saves_with_valid_tags(qapp, tmp_path, monkeypatch):
    """양성 대조 — 유효 태그(축·값 완비, 중복 없음)면 저장 성공하고 tags 가 실린다."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))  # 지오메트리 INI 격리(ST-11)
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    reg = JobRegistry(tmp_path / "jobs")
    wiz = JobEditorWizard(reg)
    wiz.template_path = "/t.hwpx"
    wiz.model = _complete_model()
    wiz._save_page.ed_name.setText("정상작업")
    wiz._save_page.ed_pattern.setText("공고-{{공고명}}")
    wiz._save_page._add_tag_row("금액구간", "1억미만")
    wiz._save_page._add_tag_row("", "")  # 빈 행은 무시되고 저장을 막지 않는다

    saved_names: "list[str]" = []
    wiz.job_saved.connect(saved_names.append)
    wiz.accept()

    assert reg.exists("정상작업")
    assert reg.load("정상작업").tags == {"금액구간": "1억미만"}
    assert saved_names == ["정상작업"]


# --------------------------------------------------- #7 발견 예외 협소화(강등 vs 전파)
def test_initialize_page_degrades_quietly_on_io_error(qapp, tmp_path, monkeypatch):
    """#7 — 발견이 예상 IO 실패(OSError)면 후보를 조용히 비운다(편집기는 계속 뜬다)."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import job_editor as je
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[-1])

    def _boom(_jobs):
        raise OSError("disk gone")

    monkeypatch.setattr(je, "discover_tag_axes", _boom)
    page.initializePage()  # 크래시하지 않는다
    assert page._known_axes == []


def test_initialize_page_propagates_programming_regression(qapp, tmp_path, monkeypatch):
    """#7 — 시그니처·반환형 회귀(TypeError/AttributeError)는 삼키지 않고 시끄럽게 전파."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui import job_editor as je
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    page = wiz.page(wiz.pageIds()[-1])

    def _regression(_jobs):
        raise TypeError("discover_tag_axes() got unexpected shape")

    monkeypatch.setattr(je, "discover_tag_axes", _regression)
    with pytest.raises(TypeError):
        page.initializePage()  # 조용히 자동완성 끄는 대신 시끄럽게 실패
