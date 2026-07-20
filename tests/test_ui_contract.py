"""목업↔ViewModel 계약 가드 — Qt/QApplication 불필요(ViewModel 은 링1, Qt-free).

목업(docs/UI_PROTOTYPE_APPB.html)의 모든 ``data-vm="클래스.속성"`` 주석이 실제 ViewModel
표면에 존재하는지 검사한다. 목업이 겨누는 seam(ViewModel 공개 API)이 이름 변경으로 어긋나면
CI 가 실패한다 — 디자인 스펙과 구현이 조용히 갈라지지 않게(confirm-or-alarm 의 구조적 적용).
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from hwpxfiller.core.job import Job
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.gui.home_state import HomeViewModel, JobRow, TxtRow
from hwpxfiller.gui.mapping_state import MappingModel, RowState
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.template_manager_state import TemplateManagerViewModel, TemplateRow
from hwpxfiller.gui.txt_state import TxtDraftViewModel

MOCKUP = Path(__file__).resolve().parents[1] / "docs" / "UI_PROTOTYPE_APPB.html"
_NO_DIR = MOCKUP.parent / "__no_such_text_templates__"


class _StubRegistry:
    """HomeViewModel 구성용 최소 레지스트리(빈 목록) — list_jobs 계약(RC-05) 미러."""

    def list_jobs(self, *, corrupted=None):
        return []


# 목업 data-vm 이 참조할 수 있는 seam 표면 — 대표 인스턴스로 검사한다(dataclass 필드·
# __init__ 인스턴스 속성까지 잡으려면 클래스가 아니라 인스턴스에 hasattr 해야 한다).
_INSTANCES = {
    "HomeViewModel": HomeViewModel(_StubRegistry()),
    "JobRow": JobRow(
        name="", template_name="", template_missing=False,
        field_count=0, filename_pattern="", last_run_display="",
        compile_state=None, compile_badge="",  # C2 파생 컴파일 배지 seam(C4)
    ),
    "RunViewModel": RunViewModel(Job()),
    # 템플릿 관리(#13) — library_dir 미지정이면 빈 라이브러리(파일 접촉 없음).
    "TemplateManagerViewModel": TemplateManagerViewModel(library_dir=None),
    "TemplateRow": TemplateRow(
        name="", path="", state=None, badge_label="", badge_level="",
        field_count=0, compilable_n=0, skipped_n=0, stray_n=0,
    ),
    "MappingModel": MappingModel(),
    "RowState": RowState(template_field=""),
    "SelectionModel": SelectionModel(0),
    "TxtDraftViewModel": TxtDraftViewModel(TextTemplateRegistry(_NO_DIR)),
    "TxtRow": TxtRow("x", 0),
}


class _VmCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: "list[str]" = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "data-vm" and value:
                self.refs.append(value)


def _collect() -> "list[str]":
    parser = _VmCollector()
    parser.feed(MOCKUP.read_text(encoding="utf-8"))
    return parser.refs


def test_mockup_exists_and_has_annotations():
    assert MOCKUP.exists(), "목업 파일이 없습니다"
    refs = _collect()
    # 세 화면이 모두 배선됐다는 하한(회귀로 주석이 통째로 사라지면 실패).
    assert len(refs) >= 20, f"data-vm 주석이 너무 적습니다: {len(refs)}개"


def test_every_data_vm_resolves_to_a_real_viewmodel_member():
    unresolved: "list[str]" = []
    for ref in _collect():
        cls_name, _, attr = ref.partition(".")
        inst = _INSTANCES.get(cls_name)
        if inst is None or not attr or not hasattr(inst, attr):
            unresolved.append(ref)
    assert not unresolved, (
        "목업 data-vm 이 ViewModel 표면과 어긋납니다: " + ", ".join(sorted(set(unresolved)))
        + " — 목업 주석 또는 ViewModel API 를 맞추세요(docs/UI_CONTRACT.md)."
    )


def test_all_three_viewmodels_are_referenced():
    seen = {r.split(".")[0] for r in _collect()}
    for required in (
        "HomeViewModel", "RunViewModel", "MappingModel",
        "SelectionModel", "TxtDraftViewModel",
    ):
        assert required in seen, f"{required} 를 겨누는 목업 요소가 없습니다"
