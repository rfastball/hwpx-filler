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
    # 삭제 = 30일 휴지통 이동 + 최근 1건 복원.
    res1 = ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "회의결과.txt")})
    assert res1["undo"] is True and not (tp / "txt" / "회의결과.txt").exists()
    restored = ctrl.dispatch("undo_delete", {})
    assert restored == {"ok": True, "name": "회의결과"}
    assert (tp / "txt" / "회의결과.txt").exists()
    ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "회의결과.txt")})
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


def test_delete_hwpx_soft_delete_and_undo(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    raw = str(tp / "lib" / "raw.hwpx")
    r1 = ctrl.dispatch("delete", {"media": "hwpx", "path": raw})
    assert r1["undo"] is True
    assert not (tp / "lib" / "raw.hwpx").exists()
    assert "raw.hwpx" not in _names(ctrl.snapshot()["hwpx"])
    ctrl.dispatch("undo_delete", {})
    assert (tp / "lib" / "raw.hwpx").exists()


def test_undo_delete_reports_missing_and_conflicting_slots(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    assert ctrl.dispatch("undo_delete", {}) == {
        "ok": False, "error": "복원할 최근 템플릿이 없습니다."
    }

    original = tp / "txt" / "온나라_기안.txt"
    ctrl.dispatch("delete", {"media": "txt", "path": str(original)})
    _media, _path, trashed, _group = ctrl._deleted_template_slot
    trashed.unlink()
    assert ctrl.dispatch("undo_delete", {}) == {
        "ok": False, "error": "복원할 템플릿이 휴지통에 없습니다."
    }

    ctrl.dispatch("txt_new", {"name": "충돌", "content": "원본"})
    conflict = tp / "txt" / "충돌.txt"
    ctrl.dispatch("delete", {"media": "txt", "path": str(conflict)})
    conflict.write_text("새 파일", encoding="utf-8")
    assert ctrl.dispatch("undo_delete", {}) == {
        "ok": False, "error": "같은 이름의 템플릿이 이미 있어 복원할 수 없습니다."
    }


def test_import_cleans_partial_file_on_copy_failure(tmp_path, monkeypatch):
    """#137 리뷰 F6 — 복사 중 실패하면 부분 파일을 걷어내고 재던진다(잘린 사본이 목록에
    남아 충돌 접미가 재시도를 막는 것을 방지)."""
    import hwpxfiller.webapp.screen_template as st

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    (ext / "협조전.txt").write_text("원본", encoding="utf-8")

    def boom(src, dst):
        Path(dst).write_text("부분", encoding="utf-8")  # 목적지 부분 생성 후 실패
        raise OSError("disk full")

    monkeypatch.setattr(st.shutil, "copy2", boom)
    with pytest.raises(OSError):
        ctrl.import_into_library(str(ext / "협조전.txt"))
    assert not (tp / "txt" / "협조전.txt").exists()  # 반가져오기 잔재 없음


def test_empty_hint_points_to_import_not_removed_folder_picker(tmp_path, monkeypatch):
    """#137 리뷰 F7 — 첫 실행(고정 루트 부재)에 폐기된 「폴더 선택」이 아니라 「가져오기」로 안내."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    txt_dir = tmp_path / "txt"
    txt_dir.mkdir()
    ctrl = TemplateController(
        TextTemplateRegistry(txt_dir), lambda s, x: None, library_dir=tmp_path / "nolib"
    )
    hint = ctrl.snapshot()["hwpx"]["empty_hint"]
    assert "가져오기" in hint and "폴더 선택" not in hint


def test_trash_is_not_rediscovered_as_template(tmp_path, monkeypatch):
    """#267 리뷰 — 삭제=루트 밑 ``.trash`` 이동이라, 재귀 스캔이 그 하위트리를 제외하지
    않으면 삭제한 템플릿이 ``타임스탬프-uuid-이름`` 으로 즉시 목록에 재등장한다(HWPX·TXT
    공통). 삭제가 삭제로 보여야 하고, 파일은 30일 보관소에 남아야 한다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("delete", {"media": "hwpx", "path": str(tp / "lib" / "raw.hwpx")})
    ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "온나라_기안.txt")})
    snap = ctrl.snapshot()
    assert _names(snap["hwpx"]) == {"comp.hwpx"}
    assert _names(snap["txt"]) == set()
    # 파일 자체는 휴지통에 살아 있다(복원 재료) — 목록에서만 사라진다.
    assert list((tp / "lib" / ".trash").iterdir())
    assert list((tp / "txt" / ".trash").iterdir())


def test_undo_restores_group_assignment(tmp_path, monkeypatch):
    """#269 리뷰 — 삭제 직후 관측 push 의 reconcile 이 사라진 키의 그룹 지정을 영구
    제거하므로, 복원은 슬롯에 떠 둔 **삭제 시점 그룹**으로 재지정해야 한다(파일만 돌아와
    조용히 「그룹 없음」이 되는 것 금지)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    ctrl.dispatch("delete", {"media": "hwpx", "path": str(tp / "lib" / "raw.hwpx")})
    ctrl.snapshot()  # 삭제 직후 관측 — 고아 지정은 정리된다(결정 8 유지)
    assert settings.load_template_group_map("hwpx") == {}
    assert ctrl.dispatch("undo_delete", {})["ok"] is True
    assert _item(ctrl.snapshot()["hwpx"], "raw.hwpx")["group"] == "입찰"
    assert settings.load_template_group_map("hwpx") == {"raw.hwpx": "입찰"}


def test_undo_keeps_slot_when_group_restore_fails(tmp_path, monkeypatch):
    """#280 리뷰 — 그룹 복원(설정 쓰기)까지 성공해야 슬롯을 비운다: 실패 후 슬롯을 이미
    비웠다면 재시도가 '복원할 템플릿이 없습니다'로 막히고 템플릿은 조용히 「그룹 없음」이
    된다. 실패 시 파일 이동을 되돌려 Undo 재시도를 가능하게 남긴다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    ctrl.dispatch("delete", {"media": "hwpx", "path": str(tp / "lib" / "raw.hwpx")})
    trashed = ctrl._deleted_template_slot[2]

    original_set_group = ctrl.hwpx_groups.set_group
    monkeypatch.setattr(
        ctrl.hwpx_groups, "set_group",
        lambda *a, **k: (_ for _ in ()).throw(OSError("설정 디렉터리 쓰기 불가")),
    )
    with pytest.raises(OSError):
        ctrl.dispatch("undo_delete", {})
    # 파일은 휴지통으로 롤백, 슬롯은 생존(재시도 재료 보존).
    assert trashed.exists() and not (tp / "lib" / "raw.hwpx").exists()
    assert ctrl._deleted_template_slot is not None

    monkeypatch.setattr(ctrl.hwpx_groups, "set_group", original_set_group)
    assert ctrl.dispatch("undo_delete", {})["ok"] is True
    assert _item(ctrl.snapshot()["hwpx"], "raw.hwpx")["group"] == "입찰"


def test_txt_undo_restore_holds_writer_lock(tmp_path, monkeypatch):
    """#268 리뷰 — TXT 복원의 존재 검사~``replace`` 는 공유 writer 락 임계구역이어야
    한다(새 템플릿·템플릿으로 저장과 교차 시 조용한 덮어쓰기 금지)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "온나라_기안.txt")})
    calls: list = []
    real = ctrl.text_registry.write_lock

    def spy():
        calls.append(True)
        return real()

    monkeypatch.setattr(ctrl.text_registry, "write_lock", spy)
    assert ctrl.dispatch("undo_delete", {})["ok"] is True
    assert calls, "TXT 복원이 공유 writer 락을 잡지 않았다"


def test_txt_undo_group_restore_and_rollback_run_inside_writer_lock(tmp_path, monkeypatch):
    """#280 리뷰 3R — 그룹 복원(과 그 실패 롤백)까지 임계구역 **안**이어야 한다: 이동만
    락으로 덮으면, 락 해제 후 동시 writer 가 같은 이름을 새로 쓴 뒤 설정 쓰기가 실패했을
    때 롤백 replace 가 그 새 내용을 무락으로 휴지통에 쓸어 넣는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "txt", "key": "온나라_기안.txt", "group": "기안"})
    ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "온나라_기안.txt")})

    events: list = []
    real_lock = ctrl.text_registry.write_lock()
    original_set_group = ctrl.txt_groups.set_group

    class SpyLock:
        def __enter__(self):
            events.append("lock_enter")
            return real_lock.__enter__()

        def __exit__(self, *exc):
            events.append("lock_exit")
            return real_lock.__exit__(*exc)

    monkeypatch.setattr(ctrl.text_registry, "write_lock", lambda: SpyLock())
    monkeypatch.setattr(
        ctrl.txt_groups, "set_group",
        lambda key, group: (events.append("set_group"), original_set_group(key, group))[1],
    )
    assert ctrl.dispatch("undo_delete", {})["ok"] is True
    assert events == ["lock_enter", "set_group", "lock_exit"]
    assert _item(ctrl.snapshot()["txt"], "온나라_기안")["group"] == "기안"


def test_delete_rejects_path_outside_library(tmp_path, monkeypatch):
    """#137 리뷰 F10 — 렌더러가 임의 경로를 실어도 라이브러리 밖 파일은 삭제 거부."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    outside = tp / "외부.txt"
    outside.write_text("건드리지마", encoding="utf-8")
    with pytest.raises(ValueError, match="목록에 없는 경로"):
        ctrl.dispatch("delete", {"media": "txt", "path": str(outside), "confirm": True})
    assert outside.exists()  # 삭제되지 않음


def test_delete_rejects_unknown_media(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="알 수 없는 형식"):
        ctrl.dispatch("delete", {"media": "pdf", "path": str(tp / "lib" / "raw.hwpx"), "confirm": True})
    assert (tp / "lib" / "raw.hwpx").exists()


def test_unknown_tpl_action_is_loud(tmp_path, monkeypatch):
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="알 수 없는 tpl 액션"):
        ctrl.dispatch("frobnicate", {})


def test_snapshot_carries_fill_precheck_warns(tmp_path, monkeypatch):
    """채움 완화 사전 고지(#154)가 카드 데이터로 흐른다 — 정상 카드엔 없음."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    marker = tp / "lib" / "marker.hwpx"
    _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>V<hp:markpenBegin/></hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
    ).save(str(marker))
    ctrl.dispatch("refresh", {})

    snap = ctrl.snapshot()
    warns = _item(snap["hwpx"], "marker.hwpx")["fill_warns"]
    assert len(warns) == 1 and "markpenBegin" in warns[0]
    assert _item(snap["hwpx"], "comp.hwpx")["fill_warns"] == []
