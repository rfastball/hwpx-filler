"""템플릿 관리(tpl) 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 화면 #13 이관 + **R-info 2부 개편(#108)** 의 회귀 심. HWPX·TXT 라이브러리 목록·상태
배지·2단계 fieldize(스캔→확인→적용)·lint·TXT CRUD 에 더해 **매체 구획 + 그룹(작업 모델
재사용)·가져오기=복사·삭제 확인·고아 복귀** 를 창 없이 확인한다. 그룹 상태는 설정 영속이라
``HWPXFILLER_HOME`` 을 tmp 로 격리한다(실 사용자 설정 오염 금지).

결정 회귀: 미리보기 액션 미노출(10F2FF98-B) · 드리프트 UI 미노출(10F2FF98-D) · 매체 구획+
그룹(#108 결정 2·3) · 가져오기=복사(결정 4) · 고아→「그룹 없음」(결정 8).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp import settings
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


def _controller(tmp_path: Path, monkeypatch) -> "tuple[TemplateController, Path, list]":
    """HWPX 라이브러리 + TXT 레지스트리를 tmp 에 꾸리고 컨트롤러를 만든다.

    그룹 상태는 설정 영속이라 ``HWPXFILLER_HOME`` 을 tmp 로 격리한 **뒤** 컨트롤러를 만든다
    (그룹 모델이 생성자에서 설정을 읽으므로 순서 중요)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
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


def _items(band: dict) -> "list[dict]":
    return [it for sec in band["sections"] for it in sec["items"]]


def _names(band: dict) -> "set[str]":
    return {it["name"] for it in _items(band)}


def _item(band: dict, name: str) -> dict:
    return next(it for it in _items(band) if it["name"] == name)


# ============================================================ 목록·배지·액션
def test_initial_lists_hwpx_and_txt(tmp_path, monkeypatch):
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    snap = ctrl.initial()
    assert _names(snap["hwpx"]) == {"raw.hwpx", "comp.hwpx"}
    assert _names(snap["txt"]) == {"온나라_기안"}
    assert _item(snap["txt"], "온나라_기안")["field_count"] == 1
    assert snap["hwpx"]["count"] == 2 and snap["txt"]["count"] == 1
    # 그룹 0개 = 퇴화 평면.
    assert snap["hwpx"]["flat"] is True and snap["hwpx"]["group_names"] == []
    assert snap["result"]["text"] == ""
    # 드리프트 UI 미노출(10F2FF98-D) — 스냅샷에 drift 표면이 없다.
    assert "drift" not in snap and not any("drift" in k for k in snap)


def test_preview_action_is_hidden_but_make_job_shown(tmp_path, monkeypatch):
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    band = ctrl.initial()["hwpx"]
    comp_actions = [a["key"] for a in _item(band, "comp.hwpx")["actions"]]
    assert "preview" not in comp_actions and "make_job" in comp_actions
    assert [a["key"] for a in _item(band, "raw.hwpx")["actions"]] == ["compile"]


def test_compile_two_phase_scan_then_apply(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    raw = str(tp / "lib" / "raw.hwpx")
    before = (tp / "lib" / "raw.hwpx").read_bytes()
    res1 = ctrl.dispatch("compile", {"path": raw})
    assert res1["needs_confirm"] is True and "변환 가능" in res1["confirm_text"]
    assert (tp / "lib" / "raw.hwpx").read_bytes() == before  # dry-run 무변형
    res2 = ctrl.dispatch("compile", {"path": raw, "confirm": True})
    assert res2["applied"] is True
    assert ctrl.snapshot()["result"]["level"] == "ok"
    assert _item(ctrl.snapshot()["hwpx"], "raw.hwpx")["state"] == "compiled"


def test_compile_no_compilable_tokens_is_inline_not_confirm(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    res = ctrl.dispatch("compile", {"path": str(tp / "lib" / "comp.hwpx")})
    assert res.get("needs_confirm") is not True and res["applied"] is False
    assert "변환 가능한 토큰이 없습니다" in ctrl.snapshot()["result"]["text"]


def test_review_lints_and_reports(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    res = ctrl.dispatch("review", {"path": str(tp / "lib" / "raw.hwpx")})
    assert res["ok"] is True and "검토" in ctrl.snapshot()["result"]["text"]


# ================================================================ TXT 저작
def test_txt_new_edit_delete_roundtrip(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("txt_new", {"name": "회의결과", "content": "{{안건}}"})
    assert (tp / "txt" / "회의결과.txt").read_text(encoding="utf-8") == "{{안건}}"
    ctrl.dispatch("txt_edit", {"path": str(tp / "txt" / "회의결과.txt"), "content": "{{안건}} {{일시}}"})
    assert (tp / "txt" / "회의결과.txt").read_text(encoding="utf-8") == "{{안건}} {{일시}}"
    # 삭제 = 공통 delete 액션(매체 명시) · 확인 라운드트립.
    res1 = ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "회의결과.txt")})
    assert res1["needs_confirm"] is True and (tp / "txt" / "회의결과.txt").exists()
    assert "빠른 기안" in res1["confirm_text"]
    ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "회의결과.txt"), "confirm": True})
    assert not (tp / "txt" / "회의결과.txt").exists()


def test_txt_new_duplicate_and_bad_name_are_loud(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="이미 같은 이름"):
        ctrl.dispatch("txt_new", {"name": "온나라_기안", "content": "x"})
    with pytest.raises(ValueError, match="경로 문자"):
        ctrl.dispatch("txt_new", {"name": "a/b", "content": "x"})
    with pytest.raises(ValueError, match="이름을 입력"):
        ctrl.dispatch("txt_new", {"name": "  ", "content": "x"})


# =============================================== 매체 구획 + 그룹(결정 2·3)
def test_set_group_partitions_and_persists(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    band = ctrl.snapshot()["hwpx"]
    assert band["flat"] is False and "입찰" in band["group_names"]
    by = {s["group"]: s for s in band["sections"]}
    assert {it["name"] for it in by["입찰"]["items"]} == {"raw.hwpx"}
    assert {it["name"] for it in by[""]["items"]} == {"comp.hwpx"}  # 미지정 = 「그룹 없음」
    # 새 컨트롤러(설정에서 복원)도 같은 구획 — 영속 실증.
    ctrl2 = TemplateController(
        TextTemplateRegistry(tp / "txt"), lambda s, x: None, library_dir=tp / "lib"
    )
    assert "입찰" in ctrl2.snapshot()["hwpx"]["group_names"]


def test_group_chip_shown_only_for_ungrouped(tmp_path, monkeypatch):
    """＋그룹지정 어포던스는 「그룹 없음」에만(결정 2) — 스냅샷 group 값이 렌더 근거."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    band = ctrl.snapshot()["hwpx"]
    assert _item(band, "raw.hwpx")["group"] == "입찰"      # 그룹 있음 → 칩 없음
    assert _item(band, "comp.hwpx")["group"] == ""         # 무그룹 → 칩 노출


def test_toggle_group_collapse_persists(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    ctrl.dispatch("toggle_group", {"media": "hwpx", "group": "입찰"})
    sec = {s["group"]: s for s in ctrl.snapshot()["hwpx"]["sections"]}["입찰"]
    assert sec["collapsed"] is True
    assert settings.load_template_collapsed_groups("hwpx") == ["입찰"]  # 매체별 영속


def test_rename_group_merge_needs_confirm(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "comp.hwpx", "group": "수의"})
    r = ctrl.dispatch("rename_group", {"media": "hwpx", "group": "수의", "new": "입찰"})
    assert r["needs_confirm"] is True and r["kind"] == "merge_group" and r["target"] == 1
    ctrl.dispatch("rename_group", {"media": "hwpx", "group": "수의", "new": "입찰", "confirm": True})
    assert ctrl.snapshot()["hwpx"]["group_names"] == ["입찰"]


def test_disband_group_returns_to_ungrouped(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    r = ctrl.dispatch("disband_group", {"media": "hwpx", "group": "입찰"})
    assert r["needs_confirm"] is True and r["count"] == 1
    ctrl.dispatch("disband_group", {"media": "hwpx", "group": "입찰", "confirm": True})
    band = ctrl.snapshot()["hwpx"]
    assert band["flat"] is True and band["group_names"] == []


def test_orphan_group_returns_to_ungrouped_after_delete(tmp_path, monkeypatch):
    """Explorer 삭제/이동으로 키가 사라진 지정은 고아 → 「그룹 없음」 복귀 + reconcile 설정 정리(결정 8)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    (tp / "lib" / "raw.hwpx").unlink()  # 파일이 사라짐
    ctrl.dispatch("refresh", {})
    assert "입찰" not in ctrl.snapshot()["hwpx"]["group_names"]
    assert settings.load_template_group_map("hwpx") == {}  # reconcile 이 유령 지정 정리


def test_media_groups_are_isolated(tmp_path, monkeypatch):
    """같은 이름 그룹이 두 매체에 독립(결정 3) — hwpx 지정이 txt 구획을 건드리지 않는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    snap = ctrl.snapshot()
    assert snap["hwpx"]["group_names"] == ["입찰"]
    assert snap["txt"]["group_names"] == [] and snap["txt"]["flat"] is True


# ==================================================== 가져오기·삭제(결정 4)
def test_import_routes_by_extension_and_is_independent(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    src_txt = ext / "협조전.txt"
    src_txt.write_text("원본", encoding="utf-8")
    _write_compiled(ext / "용역.hwpx")

    assert ctrl.import_into_library(str(src_txt)) == "협조전.txt"
    assert ctrl.import_into_library(str(ext / "용역.hwpx")) == "용역.hwpx"
    # 확장자로 매체 루트 라우팅.
    assert (tp / "txt" / "협조전.txt").exists() and (tp / "lib" / "용역.hwpx").exists()
    # 원본 후속 수정은 라이브러리 사본에 불파급(복사=참조 아님).
    src_txt.write_text("수정됨", encoding="utf-8")
    assert (tp / "txt" / "협조전.txt").read_text(encoding="utf-8") == "원본"
    # 사본은 「그룹 없음」에서 시작.
    snap = ctrl.snapshot()
    assert _item(snap["txt"], "협조전")["group"] == ""
    assert _item(snap["hwpx"], "용역.hwpx")["group"] == ""


def test_import_name_collision_suffixes(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    (ext / "온나라_기안.txt").write_text("다른내용", encoding="utf-8")
    name = ctrl.import_into_library(str(ext / "온나라_기안.txt"))
    assert name == "온나라_기안 (2).txt"  # 조용한 덮어쓰기 금지
    assert (tp / "txt" / "온나라_기안.txt").read_text(encoding="utf-8") == "제목: {{공고명}}"


def test_import_bad_extension_is_loud(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    (ext / "x.pdf").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=".hwpx 또는 .txt"):
        ctrl.import_into_library(str(ext / "x.pdf"))


def test_delete_hwpx_confirm_roundtrip(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    raw = str(tp / "lib" / "raw.hwpx")
    r1 = ctrl.dispatch("delete", {"media": "hwpx", "path": raw})
    assert r1["needs_confirm"] is True and "다시 연결" in r1["confirm_text"]
    assert (tp / "lib" / "raw.hwpx").exists()
    ctrl.dispatch("delete", {"media": "hwpx", "path": raw, "confirm": True})
    assert not (tp / "lib" / "raw.hwpx").exists()
    assert "raw.hwpx" not in _names(ctrl.snapshot()["hwpx"])


def test_unknown_tpl_action_is_loud(tmp_path, monkeypatch):
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="알 수 없는 tpl 액션"):
        ctrl.dispatch("frobnicate", {})
