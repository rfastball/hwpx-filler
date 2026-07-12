"""RC-27 — Qt 표준 문자열(qtbase) 한국어 번역기 설치.

PySide6 는 번역을 자동 로드하지 않는다 — 양 제품 부트스트랩이 각자
``install_korean_translator``(제품 간 임포트 금지 규칙에 따라 사본)를 불러
위저드 Back/Next/Cancel·파괴적 확인 &Yes/&No 를 한국어로 만든다.
헬퍼는 설치된 QTranslator 를 돌려줘 공유 QApplication 에서 원복 가능하다.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_filler_translator_translates_wizard_buttons(qapp):
    """qtbase_ko 설치 후 위저드 표준 버튼(Back/Next/Cancel)이 한국어로 렌더된다."""
    from PySide6.QtWidgets import QWizard

    from hwpxfiller.gui.app import install_korean_translator

    tr = install_korean_translator(qapp)
    try:
        assert tr is not None, "qtbase_ko 설치 실패 — 조용한 폴백 금지(RC-27)"
        wiz = QWizard()
        assert "뒤로" in wiz.buttonText(QWizard.WizardButton.BackButton)
        assert "다음" in wiz.buttonText(QWizard.WizardButton.NextButton)
        assert "취소" in wiz.buttonText(QWizard.WizardButton.CancelButton)
    finally:
        if tr is not None:
            qapp.removeTranslator(tr)  # 공유 QApplication 원복


def test_diff_translator_translates_standard_dialog_strings(qapp):
    """hwpxdiff 사본 헬퍼도 동일하게 설치된다 — 표준 다이얼로그 Yes/Cancel 한국어."""
    from PySide6.QtCore import QCoreApplication

    from hwpxdiff.app import install_korean_translator

    tr = install_korean_translator(qapp)
    try:
        assert tr is not None, "qtbase_ko 설치 실패 — 조용한 폴백 금지(RC-27)"
        assert QCoreApplication.translate("QPlatformTheme", "&Yes") == "예(&Y)"
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "취소"
    finally:
        if tr is not None:
            qapp.removeTranslator(tr)


def test_translator_load_failure_warns_loudly(qapp, monkeypatch, capsys):
    """로드 실패는 조용한 폴백이 아니라 stderr 경고 + None 반환(확인-또는-경보)."""
    from PySide6.QtCore import QTranslator

    monkeypatch.setattr(QTranslator, "load", lambda self, *a, **k: False)
    from hwpxfiller.gui.app import install_korean_translator

    assert install_korean_translator(qapp) is None
    assert "qtbase_ko" in capsys.readouterr().err


def test_both_bootstraps_install_translator():
    """양 제품 main() 이 헬퍼를 실제로 부른다 — main 은 이벤트 루프라 소스 게이트로 검증."""
    import inspect

    import hwpxdiff.app as diff_app
    import hwpxfiller.gui.app as filler_app

    for mod in (filler_app, diff_app):
        assert "install_korean_translator(app)" in inspect.getsource(mod.main), (
            f"{mod.__name__}.main() 이 한국어 번역기를 설치하지 않는다(RC-27 회귀)"
        )
