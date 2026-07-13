"""파괴적 확인 통일(RC-15) 회귀 — 공용 헬퍼 의미론 + 3개 파괴 지점의 강화 계약.

RC-15 실증(P1): 축약형 ``QMessageBox.question`` 은 기본 버튼 미지정 시 Qt 가 Yes 를
자동 기본으로 승격해 **Enter 반사 1타로 파괴가 확정**됐다. 여기서는
(1) :func:`~hwpxfiller.gui.confirm.confirm_destructive` 가 기본=취소·한국어 라벨을
소유하는지, (2) 베이스 덮어쓰기(P5a/P5b)·작업 덮어쓰기(P6)·작업 삭제가 그 헬퍼를
경유하며 파괴 대상을 구체 이름으로 재진술하는지를 못박는다.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from hwpxfiller.core.job import Job, JobRegistry  # noqa: E402
from hwpxfiller.core.mapping import FieldMapping, MappingProfile  # noqa: E402
from hwpxfiller.core.mapping_base import MappingBaseRegistry  # noqa: E402
from hwpxfiller.gui.confirm import _build_confirm_box, confirm_destructive  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _profile(name="확정매핑", fields=("공고명", "추정가격")) -> MappingProfile:
    return MappingProfile(name=name, mappings=[
        FieldMapping(template_field=f, source="bidNtceNm") for f in fields
    ])


# ------------------------------------------------------------ 헬퍼 의미론
def test_confirm_box_defaults_to_cancel_with_korean_labels(qapp):
    """기본 버튼=취소 + 한국어 명시 라벨 — RC-15 의 핵심 계약(ADR-E 강화 패턴)."""
    box, proceed, cancel = _build_confirm_box(None, "삭제", "작업 'A' 을(를) 삭제할까요?", "삭제")
    assert box.defaultButton() is cancel          # Enter 반사가 파괴로 귀결되지 않는 근거
    assert cancel.text() == "취소"
    assert proceed.text() == "삭제"                # 영어 Yes/No 아님 — 버튼이 행위를 말한다
    assert box.icon() == QMessageBox.Warning


def test_confirm_box_enter_reflex_lands_on_cancel(qapp):
    """P1 회귀 — Return 1타는 '취소' 클릭으로 귀결(과거: Yes 자동 기본 → 파괴 확정)."""
    box, proceed, cancel = _build_confirm_box(None, "덮어쓰기", "덮어쓸까요?", "덮어쓰기")
    box.show()
    QTest.keyClick(box, Qt.Key_Return)
    assert box.clickedButton() is cancel
    assert box.clickedButton() is not proceed


def test_confirm_destructive_true_only_on_explicit_proceed_click(qapp):
    """모달 실행 계약 — 명시 진행 클릭=True, 취소 클릭=False."""
    def click(label: str):
        def go():
            w = QApplication.activeModalWidget()
            if not isinstance(w, QMessageBox):  # 모달이 아직이면 다음 루프 턴에 재시도
                w = next(
                    (t for t in QApplication.topLevelWidgets()
                     if isinstance(t, QMessageBox) and t.isVisible()),
                    None,
                )
            if w is None:
                QTimer.singleShot(0, go)
                return
            next(b for b in w.buttons() if b.text() == label).click()
        return go

    QTimer.singleShot(0, click("삭제"))
    assert confirm_destructive(None, "삭제", "삭제할까요?", "삭제") is True

    QTimer.singleShot(0, click("취소"))
    assert confirm_destructive(None, "삭제", "삭제할까요?", "삭제") is False


# ------------------------------------------------- 작업 덮어쓰기(P6: slug 재진술)
def test_job_overwrite_confirm_names_actual_slug_victim(qapp, tmp_path, monkeypatch):
    """'예산/2026' 저장은 slug 접힘으로 '예산_2026' 을 파괴한다 — 문구가 실제
    파괴 대상을 재진술해야 하고(과거: 입력 이름만 재진술 = 거짓), 거절 시 무손상."""
    from hwpxfiller.gui import job_editor as je
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.mapping_state import MappingModel

    reg = JobRegistry(tmp_path)
    reg.save(Job(name="예산_2026", template_path="/t.hwpx", mapping=_profile(),
                 filename_pattern="ORIGINAL-{{ID}}"))

    def make_wiz():
        wiz = JobEditorWizard(reg)
        wiz.template_path = "/t.hwpx"
        wiz.model = MappingModel.from_profile(_profile())
        wiz._save_page.ed_name.setText("예산/2026")
        return wiz

    seen = {}
    monkeypatch.setattr(
        je, "confirm_destructive",
        lambda parent, title, text, label: seen.update(text=text) is not None,
    )  # update → None → False: 거절
    make_wiz().accept()
    assert "예산_2026" in seen["text"]                       # 실제 파괴 대상 명시
    assert reg.load("예산_2026").name == "예산_2026"          # 거절 → 무손상
    assert reg.load("예산_2026").filename_pattern == "ORIGINAL-{{ID}}"

    monkeypatch.setattr(je, "confirm_destructive", lambda *a, **k: True)
    make_wiz().accept()
    assert reg.load("예산/2026").name == "예산/2026"          # 확정 후에만 교체


# --------------------------------------------- 베이스 덮어쓰기(P5a·P5b: 확인 불가)
def _base_wizard(tmp_path, base_reg):
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.mapping_state import MappingModel

    wiz = JobEditorWizard(JobRegistry(tmp_path / "jobs"), base_registry=base_reg)
    wiz.model = MappingModel.from_profile(_profile())
    return wiz, wiz.page(wiz.pageIds()[2])  # MappingPage


def test_save_base_overwrite_confirms_even_without_refs(qapp, tmp_path, monkeypatch):
    """P5a 회귀 — 참조 작업 0개여도 기존 베이스 덮어쓰기는 확인을 요구한다."""
    from hwpxfiller.gui import wizard as wz

    base_reg = MappingBaseRegistry(tmp_path / "bases")
    base_reg.save(_profile("공유어휘", fields=("공고명",)))  # 필드 1개짜리 기존 베이스
    wiz, page = _base_wizard(tmp_path, base_reg)

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("공유어휘", True))
    seen = {}
    monkeypatch.setattr(
        wz, "confirm_destructive",
        lambda parent, title, text, label: seen.update(text=text) is not None,
    )  # 거절
    page._save_base()
    assert "공유어휘" in seen["text"]                               # 확인이 떴다(파괴 대상 명시)
    assert base_reg.load("공유어휘").template_fields() == ["공고명"]  # 거절 → 무손상

    monkeypatch.setattr(wz, "confirm_destructive", lambda *a, **k: True)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    page._save_base()
    assert base_reg.load("공유어휘").template_fields() == ["공고명", "추정가격"]


def test_save_base_refs_lookup_failure_states_unknown(qapp, tmp_path, monkeypatch):
    """P5b 회귀 — 참조 조회 실패를 '참조 없음'으로 오역하지 않고 '확인 불가'로 재진술."""
    from hwpxfiller.gui import wizard as wz

    base_reg = MappingBaseRegistry(tmp_path / "bases")
    base_reg.save(_profile("공유어휘"))
    wiz, page = _base_wizard(tmp_path, base_reg)

    class _BrokenRegistry:
        def list_jobs(self, **_kw):
            raise RuntimeError("레지스트리 읽기 실패")

    wiz.registry = _BrokenRegistry()
    assert page._referencing_jobs("공유어휘") is None  # 실패 = 불명(빈 리스트 아님)

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("공유어휘", True))
    seen = {}
    monkeypatch.setattr(
        wz, "confirm_destructive",
        lambda parent, title, text, label: seen.update(text=text) is not None,
    )
    page._save_base()
    assert "확인할 수 없" in seen["text"]  # '참조 여부 확인 불가' 명시


def test_referencing_jobs_unknown_when_corrupted_job_present(qapp, tmp_path):
    """손상 작업 파일이 있으면 참조 전수 확인이 불가 — []가 아니라 None(불명)."""
    base_reg = MappingBaseRegistry(tmp_path / "bases")
    jobs_dir = tmp_path / "jobs"
    reg = JobRegistry(jobs_dir)
    reg.save(Job(name="정상작업", template_path="/t.hwpx", mapping=_profile()))
    jobs_dir.joinpath("깨짐.job.json").write_text("{잘림", encoding="utf-8")

    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(reg, base_registry=base_reg)
    page = wiz.page(wiz.pageIds()[2])
    assert page._referencing_jobs("아무베이스") is None


# ------------------------------------------------------------ 작업 삭제(홈 라우트)
def test_delete_job_gated_by_destructive_confirm(qapp, tmp_path, monkeypatch):
    """홈 삭제 라우트 — 공용 헬퍼 거절=유지, 확정=삭제(과거: 무방비 2-인자 question)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.gui import confirm as confirm_mod
    from hwpxfiller.gui.app import AppController

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="지울작업", template_path="/t.hwpx", mapping=_profile()))
    ctrl = AppController(reg)

    seen = {}
    monkeypatch.setattr(
        confirm_mod, "confirm_destructive",
        lambda parent, title, text, label: seen.update(text=text, label=label) is not None,
    )  # 거절
    ctrl._delete_job("지울작업")
    assert reg.exists("지울작업")                     # 거절 → 유지
    assert "지울작업" in seen["text"] and seen["label"] == "삭제"

    monkeypatch.setattr(confirm_mod, "confirm_destructive", lambda *a, **k: True)
    ctrl._delete_job("지울작업")
    assert not reg.exists("지울작업")
