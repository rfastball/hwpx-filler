"""템플릿 관리(tpl) 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 화면 #13 이관의 회귀 심. HWPX 라이브러리 목록·상태 배지·2단계 fieldize(스캔→확인
라운드트립→적용)·lint 검토·TXT CRUD(신규/편집/삭제 확인 라운드트립) end-to-end 를 창 없이
확인한다. 실 HWPX·TXT 파일을 만들어 실제 변환·삭제까지 되읽는다(폴더 피커만 브리지 담당 —
여기선 경로 직접 주입).

결정 회귀(#13): 미리보기 액션 미노출(10F2FF98-B) · TXT 동등 관리(10F2FF98-C) · 드리프트
UI 미노출(스냅샷에 drift 키 없음, 10F2FF98-D).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_template import TemplateController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
_TOKEN_BODY = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>').encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    return pkg


def _write_raw(path: Path) -> Path:
    """평문 토큰만 든 미컴파일 템플릿(RAW) — scan/compile 대상."""
    _pkg(_TOKEN_BODY).save(str(path))
    return path


def _write_compiled(path: Path) -> Path:
    """평문 토큰을 누름틀로 컴파일한 템플릿(COMPILED) — make_job 노출·preview 은닉 대상."""
    pkg, _ = compile_document(_pkg(_TOKEN_BODY))
    pkg.save(str(path))
    return path


def _controller(tmp_path: Path) -> "tuple[TemplateController, Path, list]":
    """HWPX 라이브러리 폴더 + TXT 레지스트리를 tmp 에 꾸리고 컨트롤러를 만든다."""
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_raw(lib / "raw.hwpx")
    _write_compiled(lib / "comp.hwpx")
    txt_dir = tmp_path / "txt"
    txt_dir.mkdir()
    (txt_dir / "온나라_기안.txt").write_text("제목: {{공고명}}", encoding="utf-8")
    pushes: list = []
    ctrl = TemplateController(
        TextTemplateRegistry(txt_dir),
        lambda s, snap: pushes.append((s, snap)),
        library_dir=lib,
    )
    return ctrl, tmp_path, pushes


def test_initial_lists_hwpx_and_txt(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    snap = ctrl.initial()
    names = {r["name"] for r in snap["hwpx_rows"]}
    assert names == {"raw.hwpx", "comp.hwpx"}
    assert [r["name"] for r in snap["txt_rows"]] == ["온나라_기안"]
    assert snap["txt_rows"][0]["field_count"] == 1
    assert snap["result"]["text"] == ""
    # 드리프트 UI 미노출(10F2FF98-D) — 스냅샷에 drift 표면이 없다.
    assert "drift" not in snap and not any("drift" in k for k in snap)


def test_preview_action_is_hidden_but_make_job_shown(tmp_path):
    """COMPILED 는 [미리보기][작업 만들기] 중 미리보기를 숨기고 작업 만들기만 노출(10F2FF98-B)."""
    ctrl, _, _ = _controller(tmp_path)
    rows = {r["name"]: r for r in ctrl.initial()["hwpx_rows"]}
    comp_actions = [a["key"] for a in rows["comp.hwpx"]["actions"]]
    assert "preview" not in comp_actions
    assert "make_job" in comp_actions
    # RAW 는 누름틀 변환만.
    assert [a["key"] for a in rows["raw.hwpx"]["actions"]] == ["compile"]


def test_compile_two_phase_scan_then_apply(tmp_path):
    """1차=needs_confirm(파일 무변형), 2차=적용(상태 진행). 조용한 파괴 금지."""
    ctrl, tp, _ = _controller(tmp_path)
    raw = str(tp / "lib" / "raw.hwpx")
    before = (tp / "lib" / "raw.hwpx").read_bytes()

    res1 = ctrl.dispatch("compile", {"path": raw})
    assert res1["needs_confirm"] is True and "변환 가능" in res1["confirm_text"]
    assert (tp / "lib" / "raw.hwpx").read_bytes() == before  # dry-run — 파일 무변형

    res2 = ctrl.dispatch("compile", {"path": raw, "confirm": True})
    assert res2["applied"] is True
    assert ctrl.snapshot()["result"]["level"] == "ok"
    # 적용 후 상태가 진행(RAW → COMPILED) — 목록이 재스캔됐다.
    row = {r["name"]: r for r in ctrl.snapshot()["hwpx_rows"]}["raw.hwpx"]
    assert row["state"] == "compiled"


def test_compile_no_compilable_tokens_is_inline_not_confirm(tmp_path):
    """이미 COMPILED 파일은 변환 가능 토큰이 없다 → 확인 없이 인라인 통지(파괴 아님)."""
    ctrl, tp, _ = _controller(tmp_path)
    res = ctrl.dispatch("compile", {"path": str(tp / "lib" / "comp.hwpx")})
    assert res.get("needs_confirm") is not True and res["applied"] is False
    assert "변환 가능한 토큰이 없습니다" in ctrl.snapshot()["result"]["text"]


def test_review_lints_and_reports(tmp_path):
    ctrl, tp, _ = _controller(tmp_path)
    res = ctrl.dispatch("review", {"path": str(tp / "lib" / "raw.hwpx")})
    assert res["ok"] is True
    assert "검토" in ctrl.snapshot()["result"]["text"]


def test_txt_new_edit_delete_roundtrip(tmp_path):
    ctrl, tp, _ = _controller(tmp_path)
    # 신규
    ctrl.dispatch("txt_new", {"name": "회의결과", "content": "{{안건}}"})
    assert (tp / "txt" / "회의결과.txt").read_text(encoding="utf-8") == "{{안건}}"
    # 편집
    ctrl.dispatch("txt_edit", {"path": str(tp / "txt" / "회의결과.txt"), "content": "{{안건}} {{일시}}"})
    assert (tp / "txt" / "회의결과.txt").read_text(encoding="utf-8") == "{{안건}} {{일시}}"
    # 삭제 확인 라운드트립
    res1 = ctrl.dispatch("txt_delete", {"path": str(tp / "txt" / "회의결과.txt")})
    assert res1["needs_confirm"] is True and (tp / "txt" / "회의결과.txt").exists()
    ctrl.dispatch("txt_delete", {"path": str(tp / "txt" / "회의결과.txt"), "confirm": True})
    assert not (tp / "txt" / "회의결과.txt").exists()


def test_txt_new_duplicate_and_bad_name_are_loud(tmp_path):
    ctrl, tp, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="이미 같은 이름"):
        ctrl.dispatch("txt_new", {"name": "온나라_기안", "content": "x"})
    with pytest.raises(ValueError, match="경로 문자"):
        ctrl.dispatch("txt_new", {"name": "a/b", "content": "x"})
    with pytest.raises(ValueError, match="이름을 입력"):
        ctrl.dispatch("txt_new", {"name": "  ", "content": "x"})


def test_unknown_tpl_action_is_loud(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 tpl 액션"):
        ctrl.dispatch("frobnicate", {})
