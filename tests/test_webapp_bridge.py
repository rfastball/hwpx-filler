"""웹 프론트엔드 브리지 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 마이그레이션 토대의 회귀 심. 스파이크 Q1(링1 Qt-free)의 배당금이 살아있는지와,
화면 컨트롤러가 링1 VM 을 그대로 구동해 스냅샷을 만드는지를 창 없이 확인한다. 미지 액션은
시끄럽게 거부(confirm-or-alarm)해야 한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screens import TxtController

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"


def _controller(tmp_path: Path) -> "tuple[TxtController, list]":
    (tmp_path / "샘플기안.txt").write_text(
        "제목: {{공고명}}\n담당: {{담당자}}\n금액: {{추정가격}}", encoding="utf-8"
    )
    pushes: list = []
    ctrl = TxtController(TextTemplateRegistry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def test_importing_webapp_screens_loads_no_qt():
    """링1 을 임포트하는 컨트롤러 모듈이 PySide6/PyQt 를 한 줄도 끌어오지 않는다(스파이크 Q1).

    깨끗한 서브프로세스에서 검사 — 전체 스위트가 다른 곳에서 Qt 를 미리 로드하면 sys.modules
    검사가 위양성이 되므로(격리 필요).
    """
    # app 까지(브리지 전체 그래프 — webview 는 지연 임포트라 여기선 안 끌림).
    code = (
        "import sys; import hwpxfiller.webapp.app;"
        "qt=[m for m in sys.modules if 'PySide6' in m or 'PyQt' in m];"
        "print('QT:'+','.join(qt)); sys.exit(1 if qt else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, f"webapp.screens 임포트가 Qt 오염: {proc.stdout}{proc.stderr}"


def test_initial_snapshot_shape(tmp_path):
    ctrl, _ = _controller(tmp_path)
    init = ctrl.initial()
    assert "샘플기안" in init["templates"]
    names = [t["name"] for t in init["tokens"]]
    assert names == ["공고명", "담당자", "추정가격"]
    # 데이터 없음 → 전부 항목 없음(missing), 인덱스 0/0.
    assert all(t["state"] == "missing" for t in init["tokens"])
    assert init["record_index"] == 0 and init["record_count"] == 0
    assert set(init["missing_fields"]) == {"공고명", "담당자", "추정가격"}


def test_load_data_drives_vm_and_pushes(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격,담당자\n전산장비 구매,1000,\n비품 구매,,김담당\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))

    assert pushes, "load 후 관측 푸시가 없음"
    screen, snap = pushes[-1]
    assert screen == "txt"
    assert snap["record_count"] == 2 and snap["record_index"] == 1
    states = {t["name"]: t["state"] for t in snap["tokens"]}
    # rec1: 공고명=채움, 추정가격=채움, 담당자=빈 값(열 존재·값 빔).
    assert states == {"공고명": "fill", "추정가격": "fill", "담당자": "blank"}
    assert "전산장비 구매" in snap["render_text"]


def test_step_wraps_records(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격,담당자\nA,1,x\nB,2,y\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))
    ctrl.dispatch("step", {"delta": 1})
    assert pushes[-1][1]["record_index"] == 2
    ctrl.dispatch("step", {"delta": 1})  # 순환
    assert pushes[-1][1]["record_index"] == 1


def test_set_template_text_is_session_template(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("set_template_text", {"text": "안녕 {{이름}}"})
    snap = pushes[-1][1]
    assert snap["template_name"] == "(붙여넣은 텍스트)"
    assert [t["name"] for t in snap["tokens"]] == ["이름"]


def test_unknown_action_is_loud(tmp_path):
    """confirm-or-alarm: 미지 액션은 조용히 무시하지 않고 시끄럽게 거부."""
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 txt 액션"):
        ctrl.dispatch("frobnicate", {})


def test_data_label_is_server_owned_and_survives_paste(tmp_path):
    """P4: data_label 을 스냅샷(서버)이 소유 — run/matrix 와 정렬, 붙여넣기에도 실상태 반영.

    초기엔 빈 라벨. 데이터 로드 후 파일명이 스냅샷에 실린다. 붙여넣기(set_template_text)는
    템플릿만 바꾸고 겨눈 데이터(datasource)를 유지하므로 라벨도 유지돼야 한다 — 예전 JS 의
    명령형 클리어가 실상태와 어긋나던 균열 봉합.
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.initial()["data_label"] == ""

    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격,담당자\nA,1,x\nB,2,y\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))
    assert ctrl.snapshot()["data_label"] == "d.csv"

    # 붙여넣기 = 템플릿 교체이지 데이터 해제가 아니다 → 라벨·레코드 유지.
    ctrl.dispatch("set_template_text", {"text": "안녕 {{공고명}}"})
    snap = ctrl.snapshot()
    assert snap["data_label"] == "d.csv" and snap["record_count"] == 2


def test_win32_filter_block_derives_from_exts_and_is_double_null_terminated():
    """Win32 comdlg32 필터 블록이 EXCEL_EXTS 파생·이중 널 종결 구조인가.

    파일 다이얼로그를 pywebview WinForms(접근성 재귀 크래시) 대신 Win32 comdlg32 로 옮긴
    회귀 심(소이슈 ②). 확장자 단일 출처(EXCEL_EXTS)가 필터에 자동 반영되는지도 함께 가드.
    """
    from hwpxfiller.data.factory import EXCEL_EXTS
    from hwpxfiller.gui.file_filters import EXCEL_FILTER_PATTERN
    from hwpxcore.native.dialogs import _filter_block

    for ext in EXCEL_EXTS:
        assert f"*{ext}" in EXCEL_FILTER_PATTERN  # 확장자 추가가 필터에 자동 반영
    block = _filter_block([("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")])
    assert block.endswith("\0\0")  # 이중 널 종결(comdlg32 요구)
    assert block.count("\0") == 5  # 4항목 사이 널 3 + 종결 널 2
    assert f"엑셀/CSV 데이터 ({EXCEL_FILTER_PATTERN})" in block


def test_web_assets_present_and_wired():
    """web/ 골격이 서 있고 index.html 이 생성 토큰 CSS 와 화면 스크립트를 물었는가."""
    for rel in ("index.html", "css/tokens.css", "css/app.css",
                "js/bridge.js", "js/app.js", "js/screens/txt.js"):
        assert (WEB / rel).exists(), f"web/{rel} 없음"
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "css/tokens.css" in html and "js/bridge.js" in html
    # 4화면 레일 + txt 실화면 심.
    for scr in ("home", "editor", "run", "txt"):
        assert f'data-scr="{scr}"' in html, f"레일에 {scr} 없음"
    assert 'id="scr-txt"' in html
