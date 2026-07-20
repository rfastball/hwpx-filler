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
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"


def _frontend(tmp_path, monkeypatch):
    """WebFrontend 브리지 — 실 사용자 jobs 디렉터리를 건드리지 않게 tmp 로 우회."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    return app_mod.WebFrontend(tmp_path / "txt")


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


def test_new_draft_action_resets_session(tmp_path):
    """홈 「＋ 새 기안」의 new_draft 액션 — 세션 원자 초기화(F11, F10 「새 작업」과 대칭).

    종전 bare nav 는 직전 기안의 붙여넣은 텍스트·데이터·레코드 위치를 그대로 남겨
    라벨 '새'와 어긋났다. 초기 상태는 생성자와 같은 경로(_fresh_session) — 첫 템플릿
    자동 선택·데이터 라벨 소거.
    """
    ctrl, pushes = _controller(tmp_path)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격,담당자\nA,1,x\nB,2,y\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))
    ctrl.dispatch("step", {"delta": 1})                             # 레코드 2/2 로 이동
    ctrl.dispatch("set_template_text", {"text": "붙여넣은 {{본문}}"})  # 세션 템플릿 오염
    ctrl.dispatch("new_draft", {})
    snap = pushes[-1][1]
    assert snap["template_name"] == "샘플기안"                       # 첫 템플릿 재선택(생성자 동형)
    assert "{{공고명}}" in snap["template_text"]                     # 붙여넣기 텍스트 폐기
    assert snap["record_count"] == 0 and snap["record_index"] == 0   # 데이터 폐기
    assert snap["data_label"] == "" and snap["data_source_label"] == ""


def test_new_draft_without_templates_is_empty_session(tmp_path):
    """템플릿 루트가 비어도 new_draft 는 조용한 예외 없이 빈 세션으로 초기화된다."""
    empty = tmp_path / "empty"
    empty.mkdir()
    pushes: list = []
    ctrl = TxtController(
        TextTemplateRegistry(empty), lambda s, snap: pushes.append((s, snap))
    )
    ctrl.dispatch("new_draft", {})
    snap = pushes[-1][1]
    assert snap["template_name"] == "(붙여넣은 텍스트)" and snap["template_text"] == ""


def test_unknown_action_is_loud(tmp_path):
    """confirm-or-alarm: 미지 액션은 조용히 무시하지 않고 시끄럽게 거부."""
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 txt 액션"):
        ctrl.dispatch("frobnicate", {})


def test_data_label_is_server_owned_and_survives_paste(tmp_path):
    """P4: data_label 을 스냅샷(서버)이 소유 — run 과 정렬, 붙여넣기에도 실상태 반영.

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


# ------------------------------------------------------------- 다중 시트 확정 게이트(#33)
# 브리지가 모호(2+ 시트) 워크북을 조용히 첫 시트로 로드하지 않고 웹에 시트 확정을 요구하는지,
# 확정된 시트만 로드하고 모르는 시트는 시끄럽게 거절하는지 — 창 없이(다이얼로그 우회) 가드.


def test_pick_data_file_multi_sheet_defers_and_asks(tmp_path, monkeypatch):
    """다중 시트 = 조용히 첫 시트 로드 금지 → needs_sheet 페이로드로 확정 요구, 로드 보류."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(MULTI_SHEET))

    result = frontend.pick_data_file("editor")
    assert isinstance(result, dict) and result["needs_sheet"] is True
    assert result["path"] == str(MULTI_SHEET)
    assert result["name"] == "multi_sheet.xlsx"
    assert [s["name"] for s in result["sheets"]] == ["공고목록", "낙찰현황"]
    assert result["sheets"][0]["rows"] and result["sheets"][0]["cols"]  # 행×열 근사 동반
    # 핵심: 아직 아무 것도 로드하지 않았다(조용한 첫 시트 강등 없음).
    assert frontend.controllers["editor"].data_path == ""


@pytest.mark.parametrize("screen", ["editor", "job", "txt"])
def test_pick_data_file_multi_sheet_defers_on_every_screen(screen, tmp_path, monkeypatch):
    """pick_data_file 반환 계약은 screen-불가지 — 데이터를 붙이는 세 화면 모두 needs_sheet 로
    보류돼야 한다(리뷰 P1: txt 가 객체를 못 다뤄 첫 시트로 조용히 강등되던 회귀 차단).

    run 사망(슬라이스 3) 후 데이터-부착 화면은 editor·job·txt — 세 화면 모두 관통을 지킨다."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(MULTI_SHEET))
    result = frontend.pick_data_file(screen)
    assert isinstance(result, dict) and result["needs_sheet"] is True
    assert [s["name"] for s in result["sheets"]] == ["공고목록", "낙찰현황"]


def test_load_data_sheet_threads_confirmed_sheet_into_txt_controller(tmp_path, monkeypatch):
    """확정 시트가 브리지→컨트롤러(load_data_path sheet=)→링1 VM 까지 관통해 로드된다(리뷰 P1).

    txt 컨트롤러는 작업 없이 단독 로드 가능해 브리지 경로 검증에 쓴다 — 다른 화면
    (editor·job)의 sheet 관통은 각자의 컨트롤러 테스트가 픽스처와 함께 본다.
    """
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("txt", str(MULTI_SHEET), "낙찰현황")
    assert result == "multi_sheet.xlsx"
    txt = frontend.controllers["txt"]
    assert txt.data_label == "multi_sheet.xlsx"
    # 첫 시트(공고목록, 2건)가 아니라 확정 시트(낙찰현황, 3건)가 실렸는가 — 조용한 강등 아님.
    assert txt.snapshot()["record_count"] == 3


def test_pick_data_file_corrupt_workbook_returns_error_not_raise(tmp_path, monkeypatch):
    """손상 xlsx 의 시트 메타 조회 실패는 날것 예외로 새지 않고 ERROR: 로 시끄럽게 반환한다.

    리뷰 P2: ambiguous_sheets(=sheet_overview) 가 예외 변환 경계 밖이면 BadZipFile 이 pywebview
    Promise 로 그대로 전파돼 웹 핸들러(ERROR: 접두 검사)가 못 잡고 조용해진다.
    """
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a real zip/xlsx")  # openpyxl → BadZipFile
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(broken))
    result = frontend.pick_data_file("editor")
    assert isinstance(result, str) and result.startswith("ERROR:"), (
        f"손상 워크북이 ERROR: 로 안 돌아옴(날것 예외 유출 위험): {result!r}"
    )
    assert frontend.controllers["editor"].data_path == ""  # 로드 안 됨


def test_load_data_sheet_vanished_file_returns_error_not_raise(tmp_path, monkeypatch):
    """모달을 연 뒤 파일이 사라지면(경로 부재) load_data_sheet 의 sheet_overview 도 같은
    ERROR: 경계로 감싸져 시끄럽게 되돌린다(리뷰 P2 — load_data_sheet 측 대칭)."""
    frontend = _frontend(tmp_path, monkeypatch)
    gone = tmp_path / "gone.xlsx"  # 만들지 않음 → 조회 시 실패
    result = frontend.load_data_sheet("job", str(gone), "Sheet1")
    assert isinstance(result, str) and result.startswith("ERROR:"), (
        f"사라진 파일이 ERROR: 로 안 돌아옴: {result!r}"
    )


def test_pick_data_file_single_sheet_loads_directly(tmp_path, monkeypatch):
    """단일 시트/CSV = 물을 것이 없음 → 확정 게이트 없이 곧장 로드(파일명 반환)."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격\n전산장비,1000\n", encoding="utf-8-sig")
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(csv))

    result = frontend.pick_data_file("editor")
    assert result == "d.csv"
    assert frontend.controllers["editor"].data_path == str(csv)


def test_load_data_sheet_loads_confirmed_sheet(tmp_path, monkeypatch):
    """확정한 시트로 로드 → 그 시트의 필드가 컨트롤러에 반영(파일명 반환)."""
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("editor", str(MULTI_SHEET), "낙찰현황")
    assert result == "multi_sheet.xlsx"
    assert frontend.controllers["editor"].source_fields == ["업체명", "낙찰금액", "계약일"]


def test_load_data_sheet_rejects_unknown_sheet_loudly(tmp_path, monkeypatch):
    """모르는 시트명은 조용히 첫 시트로 강등하지 않고 시끄럽게 거절(로드 안 함)."""
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("editor", str(MULTI_SHEET), "없는시트")
    assert isinstance(result, str) and result.startswith("ERROR:")
    assert "없는시트" in result
    assert frontend.controllers["editor"].data_path == ""  # 로드되지 않음


def test_web_assets_present_and_wired():
    """web/ 골격이 서 있고 index.html 이 생성 토큰 CSS 와 화면 스크립트를 물었는가."""
    for rel in ("index.html", "css/tokens.css", "css/app.css",
                "js/bridge.js", "js/app.js", "js/screens/txt.js"):
        assert (WEB / rel).exists(), f"web/{rel} 없음"
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "css/tokens.css" in html and "js/bridge.js" in html
    # 레일 계약은 NAV_SCREENS 단일 출처(PR-5 리뷰 F7 — 3곳 하드코딩은 후속 레일 변경
    # [빠른 기안·랜딩 전환]마다 어긋난 채 초록이 된다) + txt 실화면 심.
    from test_web_dom_contract import NAV_SCREENS
    for scr in NAV_SCREENS:
        assert f'data-scr="{scr}"' in html, f"레일에 {scr} 없음"
    assert 'id="scr-txt"' in html


# ============================================================ #26 #6 — txt 2소스
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry


def test_txt_load_pool_and_nara_frozen(tmp_path):
    """즉시 기안의 풀 겨눔(UD-25 비대칭 해소) — 엑셀 참조 성공(라벨 서버 소유), 나라 동결 거절."""
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,담당자\n전산장비,김주무\n", encoding="utf-8")
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="기안데이터", kind="excel", opts={"path": str(csv)}))
    pool.save(DatasetPoolItem(name="나라쿼리", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    (tmp_path / "샘플기안.txt").write_text("제목: {{공고명}}", encoding="utf-8")
    pushes: list = []
    ctrl = TxtController(TextTemplateRegistry(tmp_path), lambda s, snap: pushes.append((s, snap)),
                         pool_registry=pool)
    res = ctrl.dispatch("load_pool", {"name": "기안데이터"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 기안데이터"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 기안데이터"
    assert snap["record"].get("공고명") == "전산장비"     # 참조 재읽기로 실 레코드 도착
    res2 = ctrl.dispatch("load_pool", {"name": "나라쿼리"})
    assert res2["ok"] is False and "동결" in res2["error"]
