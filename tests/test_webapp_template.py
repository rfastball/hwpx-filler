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

from hwpxfiller.domain.authoring import compile_document
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external import settings
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
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
    write_hwpx_package(path, _pkg(_TOKEN_BODY))
    return path


def _write_compiled(path: Path) -> Path:
    """평문 토큰을 누름틀로 컴파일한 템플릿(COMPILED) — make_job 노출·preview 은닉 대상."""
    pkg, _ = compile_document(_pkg(_TOKEN_BODY))
    write_hwpx_package(path, pkg)
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
    registry = TextTemplateRegistry(txt_dir)
    ctrl = TemplateController(
        registry,
        lambda s, snap: pushes.append((s, snap)),
        file_store=TemplateFileStore(
            lib, registry, clock=lambda: 2_000_000_000.0, new_id=lambda: "fixed-id"
        ),
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
def test_initial_serializes_bands_and_ring1_actions(tmp_path, monkeypatch):
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
    band = snap["hwpx"]
    comp_actions = [a["key"] for a in _item(band, "comp.hwpx")["actions"]]
    assert "preview" not in comp_actions and "make_job" in comp_actions
    assert [a["key"] for a in _item(band, "raw.hwpx")["actions"]] == ["compile"]


def test_compile_two_phase_scan_then_apply(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    raw = str(tp / "lib" / "raw.hwpx")
    before = (tp / "lib" / "raw.hwpx").read_bytes()
    review = ctrl.dispatch("review", {"path": raw})
    assert review["ok"] is True and "검토" in ctrl.snapshot()["result"]["text"]
    res1 = ctrl.dispatch("compile", {"path": raw})
    assert res1["needs_confirm"] is True and "변환 가능" in res1["confirm_text"]
    assert (tp / "lib" / "raw.hwpx").read_bytes() == before  # dry-run 무변형
    res2 = ctrl.dispatch("compile", {"path": raw, "confirm": True})
    assert res2["applied"] is True
    assert ctrl.snapshot()["result"]["level"] == "ok"
    assert _item(ctrl.snapshot()["hwpx"], "raw.hwpx")["state"] == "compiled"
    res = ctrl.dispatch("compile", {"path": str(tp / "lib" / "comp.hwpx")})
    assert res.get("needs_confirm") is not True and res["applied"] is False
    assert "변환 가능한 토큰이 없습니다" in ctrl.snapshot()["result"]["text"]


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


def test_txt_edit_and_read_reject_paths_outside_the_live_library(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    foreign = tp / "foreign.txt"
    foreign.write_text("do not touch", encoding="utf-8")
    with pytest.raises(ValueError, match="현재 TXT 라이브러리"):
        ctrl.dispatch("txt_edit", {"path": str(foreign), "content": "changed"})
    with pytest.raises(ValueError, match="현재 TXT 라이브러리"):
        ctrl.dispatch("txt_content", {"path": str(foreign)})
    assert foreign.read_text(encoding="utf-8") == "do not touch"

    alias = tp / "txt" / "별칭.txt"
    alias.write_text("link placeholder", encoding="utf-8")
    real_resolve = Path.resolve
    real_is_symlink = Path.is_symlink

    def resolve_link(path, *args, **kwargs):
        return foreign if path == alias else real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_link)
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == alias or real_is_symlink(path)
    )
    with pytest.raises(ValueError, match="현재 TXT 라이브러리"):
        ctrl.dispatch("txt_edit", {"path": str(alias), "content": "changed"})
    assert foreign.read_text(encoding="utf-8") == "do not touch"


# =============================================== 매체 구획 + 그룹(결정 2·3)
def test_group_partition_chip_collapse_and_persistence(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("set_group", {"media": "hwpx", "key": "raw.hwpx", "group": "입찰"})
    band = ctrl.snapshot()["hwpx"]
    assert band["flat"] is False and "입찰" in band["group_names"]
    by = {s["group"]: s for s in band["sections"]}
    assert {it["name"] for it in by["입찰"]["items"]} == {"raw.hwpx"}
    assert {it["name"] for it in by[""]["items"]} == {"comp.hwpx"}  # 미지정 = 「그룹 없음」
    assert _item(band, "raw.hwpx")["group"] == "입찰"
    assert _item(band, "comp.hwpx")["group"] == ""
    ctrl.dispatch("toggle_group", {"media": "hwpx", "group": "입찰"})
    section = {s["group"]: s for s in ctrl.snapshot()["hwpx"]["sections"]}["입찰"]
    assert section["collapsed"] is True
    assert settings.load_template_collapsed_groups("hwpx") == ["입찰"]
    # 새 컨트롤러(설정에서 복원)도 같은 구획 — 영속 실증.
    registry = TextTemplateRegistry(tp / "txt")
    ctrl2 = TemplateController(
        registry, lambda s, x: None,
        file_store=TemplateFileStore(
            tp / "lib", registry, clock=lambda: 2_000_000_000.0, new_id=lambda: "fixed-id"
        ), library_dir=tp / "lib"
    )
    assert "입찰" in ctrl2.snapshot()["hwpx"]["group_names"]


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

    # 반환 = 사본의 **전체 경로**(F8 판정 C — 편집기 채택 판정이 정확한 목적지를 안다).
    assert ctrl.import_into_library(str(src_txt)) == str(tp / "txt" / "협조전.txt")
    assert ctrl.import_into_library(str(ext / "용역.hwpx")) == str(tp / "lib" / "용역.hwpx")
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
    dest = ctrl.import_into_library(str(ext / "온나라_기안.txt"))
    assert Path(dest).name == "온나라_기안 (2).txt"  # 조용한 덮어쓰기 금지(반환=전체 경로)
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


def test_delete_speaks_once_via_toast_while_trash_retention_survives_without_surface(
    tmp_path, monkeypatch
):
    """U2 §2.12(#345) — 확인은 UndoToast **하나**, 기제는 30일 보존 그대로.

    자리 3(결과줄)은 문안 교체가 아니라 **제거**다(PR #353 1R — 토스트와 같은 말을 두 번
    하고, 되돌리기 어포던스를 든 토스트가 이긴다). 「휴지통」은 도달 표면(열어본다·골라
    복원한다·비운다)이 하나도 없어 사용자 문안에서 내렸다(표면은 별건 #350).

    **선행 상태를 실제로 만들어서 잰다**(2R): 빈 컨트롤러에서 재면 이 단언은 삭제가 결과줄을
    어떻게 다루든 늘 초록이라(초기값이 이미 "") 결함을 통과시킨다 — 실제로 1R 은 그렇게
    초록인 채 「지웠는데 직전 행동의 문장이 삭제의 결과인 것처럼 서 있는」 상태를 남겼다.
    그래서 직전 행동(TXT 생성)이 결과줄을 채운 뒤에 삭제한다.

    네 값을 묶어 잰다: ①삭제는 결과줄로 말하지 않는다(토스트 단독) ②남의 말도 남기지
    않는다(직전 행동 문장이 지워진다) ③파일은 ``.trash`` 에 실재한다(복원 재료) ④30일
    컷오프 정리가 여전히 돈다."""
    import os
    import time as time_mod

    from hwpxfiller.domain.template_status import TRASH_DIR_NAME

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    trash = tp / "txt" / TRASH_DIR_NAME
    trash.mkdir(parents=True)
    stale = trash / "0-stale-옛기안.txt"
    stale.write_text("옛것", encoding="utf-8")
    old = time_mod.time() - 31 * 24 * 60 * 60
    os.utime(stale, (old, old))

    # 선행 행동 — 결과줄을 실제로 채운다(이 문장이 삭제 뒤까지 살아남으면 안 된다).
    ctrl.dispatch("txt_new", {"name": "직전행동", "content": "{{건명}}"})
    before = ctrl.snapshot()["result"]
    assert before["text"] and before["level"] == "ok"      # 선행 상태 성립(측정 전제)

    res = ctrl.dispatch("delete", {"media": "txt", "path": str(tp / "txt" / "온나라_기안.txt")})
    assert res["undo"] is True                             # 확인·복구 경로 = 토스트 하나
    after = ctrl.snapshot()["result"]
    assert after["text"] == "" and after["level"] == "muted"
    assert "직전행동" not in after["text"]                 # 남의 말이 삭제의 결과로 읽히지 않는다
    _media, _path, trashed, _group = ctrl._deleted_template_slot
    assert trashed.exists() and trashed.parent == trash    # 보존은 실재(의무 상속)
    assert trashed.name == "2000000000-fixed-id-온나라_기안.txt"
    assert not stale.exists()                              # 30일 컷오프 정리 생존


def test_undo_delete_reports_missing_and_conflicting_slots(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    assert ctrl.dispatch("undo_delete", {}) == {
        "ok": False, "error": "복원할 최근 템플릿이 없습니다."
    }

    original = tp / "txt" / "온나라_기안.txt"
    ctrl.dispatch("delete", {"media": "txt", "path": str(original)})
    _media, _path, trashed, _group = ctrl._deleted_template_slot
    trashed.unlink()
    # 「휴지통」 없이 실패 사실만 말한다(U2 §2.12, #345 — 도달 표면 없는 장소 어휘 금지).
    assert ctrl.dispatch("undo_delete", {}) == {
        "ok": False, "error": "되돌릴 템플릿 파일을 찾을 수 없습니다."
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
    import hwpxfiller.external.template_files as st

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


# ==================================== 폴더 일괄 가져오기(#339 · U2 §2.16 narrow)
def _import_folder_fixture(tp: Path) -> Path:
    """혼합 폴더: 후보 3(.hwpx 1 + .txt 2, 그중 온나라_기안.txt 는 기존과 충돌) ·
    제외 파일 1(.pdf) · 하위 폴더 1(그 안 .txt 는 1단계 밖)."""
    ext = tp / "ext"
    (ext / "sub").mkdir(parents=True)
    (ext / "협조전.txt").write_text("{{건명}}", encoding="utf-8")
    _write_compiled(ext / "용역.hwpx")
    (ext / "명세.pdf").write_text("x", encoding="utf-8")
    (ext / "온나라_기안.txt").write_text("다른내용", encoding="utf-8")   # 충돌 후보
    (ext / "sub" / "하위.txt").write_text("{{x}}", encoding="utf-8")     # 1단계 밖
    return ext


def test_scan_import_folder_restates_and_writes_nothing(tmp_path, monkeypatch):
    """스캔 = 읽기 전용 재진술 — 매체별 건수·제외 수·충돌 수 + 완성 문안. **확정 전에는
    홈에 아무것도 쓰지 않는다**(#339). 하위 폴더는 세지도 가져오지도 않는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = _import_folder_fixture(tp)
    before_lib = set((tp / "lib").iterdir())
    before_txt = set((tp / "txt").iterdir())
    res = ctrl.scan_import_folder(str(ext))
    assert res["needs_confirm"] is True and res["folder"] == str(ext)
    assert res["hwpx"] == 1 and res["txt"] == 2
    assert res["skipped"] == 1 and res["collisions"] == 1
    # 실행이 결속될 확정 후보 목록(이름순) — PR #355 리뷰: 실행은 이 목록을 받는다.
    assert res["files"] == ["온나라_기안.txt", "용역.hwpx", "협조전.txt"]
    text = res["confirm_text"]
    assert "HWPX 서식 1건" in text and "TXT 기안 2건" in text
    assert "나머지 파일 1개는 가져오지 않습니다" in text
    assert "하위 폴더는 살펴보지 않습니다" in text
    # 「(2)」 단정 금지(PR #355 리뷰) — (2)가 이미 있으면 (3)이 붙는다: 정책만 재진술.
    assert "이름 충돌 1건" in text and "번호 접미" in text and "(2)" not in text
    # 무변이 — 라이브러리·TXT 루트에 아무것도 쓰지 않았다.
    assert set((tp / "lib").iterdir()) == before_lib
    assert set((tp / "txt").iterdir()) == before_txt


def test_scan_import_folder_empty_and_missing_are_loud(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    empty = tp / "empty"
    (empty / "sub").mkdir(parents=True)
    (empty / "명세.pdf").write_text("x", encoding="utf-8")
    res = ctrl.scan_import_folder(str(empty))
    assert res["ok"] is False and ".hwpx/.txt 파일이 없습니다" in res["error"]
    assert "하위 폴더는 살펴보지 않습니다" in res["error"]   # sub 가 있으니 사유 병기
    with pytest.raises(ValueError, match="폴더를 찾을 수 없습니다"):
        ctrl.scan_import_folder(str(tp / "없는폴더"))


def test_import_folder_routes_media_suffixes_collision_and_skips_subfolders(
    tmp_path, monkeypatch
):
    """실행 = 확정 목록을 복사 몸통으로 반복(복사 권위 단일) — 확장자 매체 라우팅 · 충돌
    번호 접미 · 하위 폴더 미반입 · 「그룹 없음」 시작 · 배치 요약 결과 줄 · **push 1회**
    (PR #355 리뷰: 항목별 전체 리프레시·재렌더 유예, 완료 후 한 번)."""
    ctrl, tp, pushes = _controller(tmp_path, monkeypatch)
    ext = _import_folder_fixture(tp)
    manifest = ctrl.scan_import_folder(str(ext))["files"]
    before_pushes = len(pushes)
    res = ctrl.import_folder(str(ext), manifest)
    assert res == {"ok": True, "imported": 3, "total": 3, "failed": []}
    assert len(pushes) == before_pushes + 1              # 배치 완료 후 1회만 민다
    assert (tp / "lib" / "용역.hwpx").exists()                       # hwpx → 라이브러리
    assert (tp / "txt" / "협조전.txt").exists()                      # txt → 텍스트 레지스트리
    assert (tp / "txt" / "온나라_기안 (2).txt").read_text(encoding="utf-8") == "다른내용"
    assert (tp / "txt" / "온나라_기안.txt").read_text(encoding="utf-8") == "제목: {{공고명}}"
    assert not (tp / "txt" / "하위.txt").exists()                    # 1단계 밖 미반입
    snap = ctrl.snapshot()
    assert _item(snap["hwpx"], "용역.hwpx")["group"] == ""           # 「그룹 없음」 시작
    assert _item(snap["txt"], "협조전")["group"] == ""
    assert "3건을 가져왔습니다" in snap["result"]["text"]
    assert snap["result"]["level"] == "ok"


def test_import_folder_partial_failure_keeps_successes_and_restates_reasons(
    tmp_path, monkeypatch
):
    """중간 1건 실패 주입 — 앞선 성공분은 남고 실패분 부분 파일은 사라지며(단건 무잔재
    상속), 결과 줄이 건수·사유를 말한다(#339: 걷어내고 계속 + 사유 병기)."""
    import hwpxfiller.external.template_files as st

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = _import_folder_fixture(tp)
    real = st.shutil.copy2

    def flaky(src, dst):
        if Path(src).name == "용역.hwpx":  # 이름순(온나라<용역<협조전) **가운데** 건을 떨군다
            Path(dst).write_text("부분", encoding="utf-8")  # 부분 파일 청소(무잔재)도 함께 검증
            raise OSError("디스크 오류")
        return real(src, dst)

    monkeypatch.setattr(st.shutil, "copy2", flaky)
    res = ctrl.import_folder(str(ext), ["온나라_기안.txt", "용역.hwpx", "협조전.txt"])
    assert res["ok"] is False and res["imported"] == 2 and res["total"] == 3
    assert res["failed"] == [{"name": "용역.hwpx", "error": "디스크 오류"}]
    assert (tp / "txt" / "협조전.txt").exists()                      # 성공분 잔존
    assert (tp / "txt" / "온나라_기안 (2).txt").exists()
    assert not (tp / "lib" / "용역.hwpx").exists()                   # 실패분 부분 파일 무잔재
    result = ctrl.snapshot()["result"]
    assert "3건 중 2건 등록" in result["text"] and "1건 실패" in result["text"]
    assert "용역.hwpx" in result["text"] and "디스크 오류" in result["text"]
    assert result["level"] == "warn"


def test_import_folder_is_bound_to_confirmed_manifest_not_a_rescan(tmp_path, monkeypatch):
    """PR #355 리뷰 — 실행은 **확정 시점 후보 목록**에 결속된다(재스캔 금지).

    스캔~확정 사이 폴더가 바뀌는 두 방향을 다 잰다: ①새로 온 파일은 재진술에 없었으므로
    들어오지 않는다(확인 안 된 반입 금지) ②확정된 파일이 사라졌으면 그 건만 부분 실패로
    사유를 병기하고 나머지는 계속한다. ③목록 형태 검증 — basename 밖(상위 탈출)·비허용
    확장자는 loud 거절(임의 경로 반입 승격 차단)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = _import_folder_fixture(tp)
    manifest = ctrl.scan_import_folder(str(ext))["files"]

    (ext / "확정뒤추가.txt").write_text("{{몰래}}", encoding="utf-8")   # ① 스캔 뒤 등장
    (ext / "협조전.txt").unlink()                                       # ② 스캔 뒤 소실

    def unexpected_rescan(_folder):
        raise AssertionError("확정 import가 폴더를 다시 스캔했습니다")

    monkeypatch.setattr(ctrl._files, "folder_candidates", unexpected_rescan)

    res = ctrl.import_folder(str(ext), manifest)
    assert res["imported"] == 2 and res["total"] == 3
    assert res["failed"] == [{"name": "협조전.txt", "error": "확정 뒤 폴더에서 사라졌습니다"}]
    assert not (tp / "txt" / "확정뒤추가.txt").exists()   # 확인 안 된 파일은 들어오지 않는다
    result = ctrl.snapshot()["result"]
    assert "협조전.txt" in result["text"] and "사라졌습니다" in result["text"]

    with pytest.raises(ValueError, match="목록에 올 수 없는 항목"):
        ctrl.import_folder(str(ext), ["../탈출.txt"])
    with pytest.raises(ValueError, match="목록에 올 수 없는 항목"):
        ctrl.import_folder(str(ext), ["명세.pdf"])
    with pytest.raises(ValueError, match="목록이 비어"):
        ctrl.import_folder(str(ext), [])


def test_batch_txt_copy_joins_the_registry_writer_lock(tmp_path, monkeypatch):
    """PR #355 P1 — 배치 TXT 복사는 **공유 TXT writer 잠금 축**에 선다.

    배치가 도는 동안 편집기는 살아 있고 pywebview 는 다른 네이티브 호출을 동시에 돌린다.
    가져오기 잠금만 잡으면 「새 TXT」·편집·복원이 서로를 모른 채 같은 이름을 겨눠, 배치가
    「비었다」고 고른 목적지를 그 사이 사용자가 채우고 ``copy2`` 가 그 내용을 덮는다(충돌
    접미가 지켜야 할 사용자 내용의 조용한 소실).

    복사 한복판에서 **다른 스레드**가 같은 basename 으로 ``txt_new`` 를 시도하게 해 잰다:
    ①그 writer 는 복사가 끝날 때까지 **실제로 대기한다**(잠금 축 참여의 실증 — 대기 없이
    지나가면 이 단언이 죽는다) ②대기 뒤에는 파일이 이미 있으므로 loud 거절(조용한 덮어쓰기
    금지) ③배치 사본의 내용이 온전하다.

    획득 순서 규약(_folder_import_lock → _import_lock → write_lock)이 지켜지는 증거이기도
    하다: 역순 획득이 있으면 이 테스트가 join 시간초과로 멈춘다."""
    import threading

    import hwpxfiller.external.template_files as st

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    (ext / "온나라_기안.txt").write_text("가져온 내용", encoding="utf-8")  # 기존과 동명 → (2)

    real = st.shutil.copy2
    rival_started = threading.Event()
    rival_error: list = []
    state: dict = {}

    def rival() -> None:
        rival_started.set()
        try:
            # 배치가 방금 「비었다」고 고른 그 이름을 정확히 겨눈다.
            ctrl.dispatch("txt_new", {"name": "온나라_기안 (2)", "content": "사용자가 쓴 내용"})
        except Exception as exc:  # noqa: BLE001 — loud 거절을 값으로 회수
            rival_error.append(str(exc))

    def copy_with_rival(src, dst):
        if Path(src).name == "온나라_기안.txt" and "thread" not in state:
            t = threading.Thread(target=rival)
            state["thread"] = t
            t.start()
            rival_started.wait(2)
            t.join(0.3)                       # 잠금이 있으면 여기서 못 끝난다
            state["rival_blocked"] = t.is_alive()
        return real(src, dst)

    monkeypatch.setattr(st.shutil, "copy2", copy_with_rival)
    res = ctrl.import_folder(str(ext), ["온나라_기안.txt"])
    state["thread"].join(5)
    assert not state["thread"].is_alive(), "경쟁 writer 가 풀려나지 못했습니다(교착 의심)."

    assert state["rival_blocked"] is True, (
        "복사 중인데 다른 TXT writer 가 그대로 통과했습니다 — 두 쓰기가 서로를 모릅니다"
        "(가져오기 잠금만 잡고 공유 writer 축에 서지 않은 상태)."
    )
    assert res["imported"] == 1
    dest = tp / "txt" / "온나라_기안 (2).txt"
    assert dest.read_text(encoding="utf-8") == "가져온 내용"   # 사본이 덮이지 않았다
    assert rival_error and "이미 같은 이름" in rival_error[0]  # 뒤늦은 writer 는 loud 거절
    assert (tp / "txt" / "온나라_기안.txt").read_text(encoding="utf-8") == "제목: {{공고명}}"


def test_batch_hwpx_copy_is_serialized_with_undo_restore(tmp_path, monkeypatch):
    """PR #355 P1 후속 — HWPX 배치 복사도 **삭제 복원과 같은 writer 축**에 선다.

    「HWPX 는 공유 writer 가 없는 단일 표면」이라는 전제가 틀렸다: ``_do_undo_delete`` 의
    hwpx 갈래가 바로 그 공유 writer 다. 지운 basename 이 배치에 들어 있고 사용자가 확정
    뒤에도 살아 있는 「되돌리기」를 누르면, 잠금을 공유하지 않는 두 쪽이 그 이름을 함께
    「비었다」고 읽는다 — 복원이 원본을 되돌린 직후 ``copy2`` 가 그 위를 덮어 **복원은
    성공을 보고하는데 지운 문서는 사라진다**.

    TXT 판과 **같은 형태**로 잰다(복사 한복판에 경쟁 writer 주입): ①실제로 대기하고
    ②조용한 덮어쓰기 없이 loud 거절되며 ③양쪽 결과가 온전하고(가져온 사본 + 휴지통에
    남은 원본 = 복원 재시도 재료) ④교착이면 join 시간초과로 시끄럽게 멈춘다."""
    import threading

    import hwpxfiller.external.template_files as st

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    original_bytes = (tp / "lib" / "raw.hwpx").read_bytes()
    ctrl.dispatch("delete", {"media": "hwpx", "path": str(tp / "lib" / "raw.hwpx")})
    assert not (tp / "lib" / "raw.hwpx").exists()          # 이름이 비었다(양쪽이 노리는 자리)

    ext = tp / "ext"
    ext.mkdir()
    _write_compiled(ext / "raw.hwpx")                      # 같은 basename, 다른 내용
    imported_bytes = (ext / "raw.hwpx").read_bytes()
    assert imported_bytes != original_bytes

    real = st.shutil.copy2
    rival_started = threading.Event()
    rival_result: list = []
    state: dict = {}

    def rival() -> None:
        rival_started.set()
        rival_result.append(ctrl.dispatch("undo_delete", {}))

    def copy_with_rival(src, dst):
        if Path(src).name == "raw.hwpx" and "thread" not in state:
            t = threading.Thread(target=rival)
            state["thread"] = t
            t.start()
            rival_started.wait(2)
            t.join(0.3)                       # 같은 축이면 여기서 못 끝난다
            state["rival_blocked"] = t.is_alive()
        return real(src, dst)

    monkeypatch.setattr(st.shutil, "copy2", copy_with_rival)
    res = ctrl.import_folder(str(ext), ["raw.hwpx"])
    state["thread"].join(5)
    assert not state["thread"].is_alive(), "복원 스레드가 풀려나지 못했습니다(교착 의심)."

    assert state["rival_blocked"] is True, (
        "복사 중인데 삭제 복원이 그대로 통과했습니다 — 두 writer 가 서로를 모릅니다"
        "(HWPX 가 공유 writer 축에 서지 않은 상태)."
    )
    assert res["imported"] == 1
    # 조용한 덮어쓰기 없음: 뒤늦은 복원은 loud 거절되고, 가져온 사본이 그 자리에 온전하다.
    assert rival_result and rival_result[0]["ok"] is False
    assert "이미 있어 복원할 수 없습니다" in rival_result[0]["error"]
    assert (tp / "lib" / "raw.hwpx").read_bytes() == imported_bytes
    # 지운 문서도 사라지지 않았다 — 휴지통 원본이 그대로라 복원 재시도 재료가 남는다.
    _media, _path, trashed, _group = ctrl._deleted_template_slot
    assert trashed.exists() and trashed.read_bytes() == original_bytes


def test_import_folder_rejects_concurrent_batch_loudly(tmp_path, monkeypatch):
    """PR #355 2R — 배치 진행 중 재실행의 판정 정본은 tpl 권위 **한 곳**(비차단 잠금).

    JS in-flight 플래그(어포던스 잠금)가 뚫려도 — 재클릭·확정 모달 이중 열림 — 두 번째
    배치는 같은 목록을 번호 접미로 재반입하지 못하고 loud 거절된다. 복사 도중(첫 건의
    copy2 안에서) 같은 배치를 다시 부르는 재진입으로 결정적으로 잰다. 끝난 뒤에는 잠금이
    풀려 다음 배치가 정상 실행된다(거절이 영구 잠금이 되지 않는다)."""
    import hwpxfiller.external.template_files as st

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = _import_folder_fixture(tp)
    manifest = ctrl.scan_import_folder(str(ext))["files"]
    real = st.shutil.copy2
    raced: list = []

    def racing(src, dst):
        if not raced:  # 첫 건 복사 도중 = 배치 in-flight 한복판
            raced.append(True)
            with pytest.raises(ValueError, match="이미 진행 중"):
                ctrl.import_folder(str(ext), manifest)
        return real(src, dst)

    monkeypatch.setattr(st.shutil, "copy2", racing)
    res = ctrl.import_folder(str(ext), manifest)
    assert res["ok"] is True and res["imported"] == 3    # 본 배치는 끝까지 간다
    assert raced == [True]                               # 재진입이 실제로 시도·거절됐다
    # 이중 반입 없음 — 거절된 두 번째 배치가 접미 사본을 남기지 않았다.
    assert not (tp / "txt" / "협조전 (2).txt").exists()
    assert not (tp / "lib" / "용역 (2).hwpx").exists()
    # 배치 종료 후 잠금 해제 — 다음 배치는 정상 거동(사라진 원본은 부분 실패 사유 병기).
    monkeypatch.setattr(st.shutil, "copy2", real)
    res2 = ctrl.import_folder(str(ext), manifest)
    assert res2["imported"] == 3                         # 재실행 자체는 가능(접미로 들어간다)


def test_bridge_folder_import_two_step_validates_and_leaves_session_alone(
    tmp_path, monkeypatch
):
    """브리지 import_templates_folder(#339) — ①스캔 왕복(무변이) ②확정 목록 결속 실행
    ③payload 검증(확정·목록 없는 실행 loud) ④피커 취소 None ⑤**채택 없음**: 편집 세션·
    dirty 불변."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    fe = app_mod.WebFrontend(tmp_path / "reg_txt")
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "협조전.txt").write_text("{{건명}}", encoding="utf-8")
    monkeypatch.setattr(app_mod, "open_folder_dialog", lambda *a, **k: str(ext))

    # 편집 세션을 열어 둔다 — 폴더 가져오기는 채택하지 않는다(세션 확인도 없다).
    session_tpl = _write_compiled(tmp_path / "세션.hwpx")
    editor = fe.controllers["editor"]
    editor.load_template_path(str(session_tpl))
    editor.dispatch("skip_data", {})
    assert editor.has_unsaved_work() is True

    txt_root = fe.controllers["tpl"].text_registry.directory
    r1 = fe.import_templates_folder()
    assert r1["needs_confirm"] is True and r1["txt"] == 1
    assert r1["files"] == ["협조전.txt"]                 # 실행이 결속될 확정 목록
    assert not (txt_root / "협조전.txt").exists()        # 확정 전 무변이
    r2 = fe.import_templates_folder(r1["folder"], True, r1["files"])
    assert r2["ok"] is True and r2["imported"] == 1
    assert (txt_root / "협조전.txt").exists()
    # 세션 불변 — 템플릿·미저장 판정이 그대로다(채택 없음).
    assert editor.template_path == str(session_tpl)
    assert editor.has_unsaved_work() is True

    with pytest.raises(ValueError, match="confirm 필수"):
        fe.import_templates_folder(str(ext))             # 재진술 없는 실행 차단
    with pytest.raises(ValueError, match="폴더 경로가 비어"):
        fe.import_templates_folder("  ", True, ["협조전.txt"])
    with pytest.raises(ValueError, match="확정된 가져오기 목록이 없습니다"):
        fe.import_templates_folder(str(ext), True)       # 목록 없는 실행 차단(재스캔 금지)
    monkeypatch.setattr(app_mod, "open_folder_dialog", lambda *a, **k: None)
    assert fe.import_templates_folder() is None          # 피커 취소


# (test_empty_hint... 삭제 — empty_hint 는 tpl 화면과 함께 사망(F8 §10.17):
#  빈 밴드 안내는 편집기 「템플릿」 탭이 자기 문안으로 소유한다.)

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
    write_hwpx_package(marker, _pkg(
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>V<hp:markpenBegin/></hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
    ))
    ctrl.dispatch("refresh", {})

    snap = ctrl.snapshot()
    warns = _item(snap["hwpx"], "marker.hwpx")["fill_warns"]
    assert len(warns) == 1 and "markpenBegin" in warns[0]
    assert _item(snap["hwpx"], "comp.hwpx")["fill_warns"] == []


# (고지 ②(휘발 「기안」 폐지 재진술) 테스트 삭제 — 문안이 tpl 화면과 함께 사망(F8
#  §10.17). 고지 ①(job txt_note)은 test_webapp_job 이 계속 진다.)
