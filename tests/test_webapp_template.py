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
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.template_root import TemplateRoot
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


def _controller(
    tmp_path: Path, monkeypatch, *, migration_notice: str = ""
) -> "tuple[TemplateController, Path, list]":
    """HWPX 라이브러리 + TXT 레지스트리를 tmp 에 꾸리고 컨트롤러를 만든다.

    그룹 상태는 설정 영속이라 ``HWPXFILLER_HOME`` 을 tmp 로 격리한 **뒤** 컨트롤러를 만든다
    (그룹 모델이 생성자에서 설정을 읽으므로 순서 중요)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    # U6-A(#975): hwpx·txt 가 **같은 서식 폴더**를 읽는다 — 매체별 루트 축은 사라졌다.
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_raw(lib / "raw.hwpx")
    _write_compiled(lib / "comp.hwpx")
    (lib / "온나라_기안.txt").write_text("제목: {{공고명}}", encoding="utf-8")
    pushes: list = []
    root = TemplateRoot(default_root=lib)
    registry = TextTemplateRegistry(root.path)
    ctrl = TemplateController(
        registry,
        lambda s, snap: pushes.append((s, snap)),
        file_store=TemplateFileStore(root.path, registry),
        template_root=root,
        pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
        example_data_dir=tmp_path / "example_data",
        migration_notice=migration_notice,
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
    assert _names(snap["hwpx"]) == {"raw", "comp"}
    assert _names(snap["txt"]) == {"온나라_기안"}
    assert _item(snap["txt"], "온나라_기안")["field_count"] == 1
    assert snap["hwpx"]["count"] == 2 and snap["txt"]["count"] == 1
    # 그룹 0개 = 퇴화 평면.
    # 밴드는 언제나 평면이고 그룹 후보 목록은 싣지 않는다(U4 §2-30).
    assert snap["hwpx"]["flat"] is True and "group_names" not in snap["hwpx"]
    assert snap["result"]["text"] == ""
    # 드리프트 UI 미노출(10F2FF98-D) — 스냅샷에 drift 표면이 없다.
    assert "drift" not in snap and not any("drift" in k for k in snap)
    band = snap["hwpx"]
    comp_actions = [a["key"] for a in _item(band, "comp")["actions"]]
    assert "preview" not in comp_actions and "make_job" in comp_actions
    assert [a["key"] for a in _item(band, "raw")["actions"]] == ["compile"]


def test_compile_two_phase_scan_then_apply(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    raw = str(tp / "lib" / "raw.hwpx")
    before = (tp / "lib" / "raw.hwpx").read_bytes()
    review = ctrl.dispatch("review", {"path": raw})
    assert review["ok"] is True and "검토" in ctrl.snapshot()["result"]["text"]
    res1 = ctrl.dispatch("compile", {"path": raw})
    # 확인 본문은 두 축을 함께 재진술한다(S8-03) — 「항목 n · 선택 m · 누름틀 k」.
    assert res1["needs_confirm"] is True and "누름틀 1개" in res1["confirm_text"]
    assert (tp / "lib" / "raw.hwpx").read_bytes() == before  # dry-run 무변형
    res2 = ctrl.dispatch("compile", {"path": raw, "confirm": True})
    assert res2["applied"] is True and res2["refused"] is False
    assert ctrl.snapshot()["result"]["level"] == "ok"
    assert _item(ctrl.snapshot()["hwpx"], "raw")["state"] == "compiled"
    res = ctrl.dispatch("compile", {"path": str(tp / "lib" / "comp.hwpx")})
    assert res.get("needs_confirm") is not True and res["applied"] is False
    assert "변환할 토큰과 구간이 없습니다" in ctrl.snapshot()["result"]["text"]


# ============================================= S8-03 구간 표기 변환 · Slot 관리 동사
_NOTATION_BODY = "".join(
    f'<hp:p><hp:run charPrIDRef="0"><hp:t>{line}</hp:t></hp:run></hp:p>'
    for line in (
        "{{#항목 특약 특약 사항}}",
        "{{#선택 지체상금 지체상금 조항}}",
        "지체상금은 {{지체상금률}} 로 한다.",
        "{{/선택}}",
        "{{/항목}}",
        # 항목 밖 본문 1줄 — 삭제가 섹션을 통째로 비우지 않게(커널이 그건 거절한다).
        "발주자: {{수요기관}}",
    )
)


def _notation_template(ctrl, tmp_path: Path, body: str = _NOTATION_BODY) -> str:
    """라이브러리에 구간 표기 템플릿을 놓고 목록을 다시 읽는다."""
    path = tmp_path / "lib" / "구간.hwpx"
    write_hwpx_package(path, _pkg(body))
    ctrl.dispatch("refresh", {})
    return str(path)


def test_compile_refuses_a_notation_diagnostic_without_asking(tmp_path, monkeypatch):
    """변환 불가는 확정할 것이 아니다 — 확인 왕복 없이 사유만 재진술한다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    broken = _notation_template(
        ctrl, tp, '<hp:p><hp:run><hp:t>{{#항목 특약}}</hp:t></hp:run></hp:p>'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
    )
    before = Path(broken).read_bytes()

    result = ctrl.dispatch("compile", {"path": broken})

    assert result == {"ok": True, "applied": False, "blocked": True}
    assert "변환할 수 없습니다" in ctrl.snapshot()["result"]["text"]
    assert Path(broken).read_bytes() == before


def test_review_projects_the_slot_list(tmp_path, monkeypatch):
    """검토가 Slot 목록을 스냅샷에 세운다(판정 재조립 없이 투영 그대로)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})

    assert ctrl.snapshot()["slots"] is None  # 검토 전에는 목록이 서지 않는다
    ctrl.dispatch("review", {"path": path})

    slots = ctrl.snapshot()["slots"]
    assert slots["path"] == path and slots["name"] == "구간.hwpx"
    assert slots["rows"] == [
        {"id": "특약", "label": "특약 사항", "option_count": 1, "options": ["지체상금 조항"]}
    ]
    assert slots["summary"] == "항목 1개 · 선택 1개" and slots["diagnostics"] == []


def test_slot_rename_is_a_single_round_trip(tmp_path, monkeypatch):
    """개명은 파괴가 아니다 — 확인 없이 바로 적용하고 목록을 다시 투영한다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})

    result = ctrl.dispatch("slot_rename", {"path": path, "slot_id": "특약", "label": "새 이름"})

    assert result == {"ok": True, "slot_count": 1}
    assert ctrl.snapshot()["slots"]["rows"][0]["label"] == "새 이름"
    assert "항목 이름을 바꿨습니다" in ctrl.snapshot()["result"]["text"]
    # 빈 label 은 이름을 뗀다.
    ctrl.dispatch("slot_rename", {"path": path, "slot_id": "특약", "label": "  "})
    assert ctrl.snapshot()["slots"]["rows"][0]["label"] == ""


def test_slot_decompile_and_remove_take_two_round_trips(tmp_path, monkeypatch):
    """파괴·전이 동사는 확인 왕복을 거친다. 1차 호출은 파일을 만지지 않는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    before = Path(path).read_bytes()

    ask = ctrl.dispatch("slot_decompile", {"path": path, "slot_id": "특약"})
    assert ask["needs_confirm"] is True and ask["kind"] == "slot_decompile"
    assert "문서를 만들 수 없습니다" in ask["confirm_text"]
    assert Path(path).read_bytes() == before

    ctrl.dispatch("slot_decompile", {"path": path, "slot_id": "특약", "confirm": True})
    assert ctrl.snapshot()["slots"]["rows"] == []
    assert "표기로 되돌렸습니다" in ctrl.snapshot()["result"]["text"]

    # 다시 변환한 뒤 삭제 왕복.
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    ask = ctrl.dispatch("slot_remove", {"path": path, "slot_id": "특약"})
    assert ask["needs_confirm"] is True and "사라지는 것:" in ask["confirm_text"]
    ctrl.dispatch("slot_remove", {"path": path, "slot_id": "특약", "confirm": True})
    assert ctrl.snapshot()["slots"]["rows"] == []


#: 항목 2개짜리 표기 문서 — 「전부 되돌리기」가 재는 대상(단건과 구별되려면 2건이어야 한다).
_TWO_SLOT_BODY = "".join(
    f'<hp:p><hp:run charPrIDRef="0"><hp:t>{line}</hp:t></hp:run></hp:p>'
    for line in (
        "{{#항목 특약 특약 사항}}",
        "{{#선택 지체상금 지체상금 조항}}",
        "지체상금은 {{지체상금률}} 로 한다.",
        "{{/선택}}",
        "{{/항목}}",
        "{{#항목 부기 부기 사항}}",
        "부기: {{부기문}}",
        "{{/항목}}",
        "발주자: {{수요기관}}",
    )
)


def test_slot_decompile_all_takes_two_round_trips(tmp_path, monkeypatch):
    """전체판 풀기도 확인 왕복이다. 1차는 파일을 만지지 않고 개수·전이 결과만 재진술한다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp, _TWO_SLOT_BODY)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    assert [row["id"] for row in ctrl.snapshot()["slots"]["rows"]] == ["특약", "부기"]
    before = Path(path).read_bytes()

    ask = ctrl.dispatch("slot_decompile_all", {"path": path})

    assert ask["needs_confirm"] is True and ask["kind"] == "slot_decompile_all"
    assert "slot_id" not in ask  # 대상은 항목이 아니라 파일이다
    assert "항목 2개를 전부" in ask["confirm_text"]
    # 전이 결과 재진술은 단건 동사와 **같은 말**이어야 한다(같은 전이).
    assert "문서를 만들 수 없습니다" in ask["confirm_text"]
    assert "'누름틀·구간 변환'을 다시 하세요" in ask["confirm_text"]
    assert Path(path).read_bytes() == before

    result = ctrl.dispatch("slot_decompile_all", {"path": path, "confirm": True})

    assert result == {"ok": True, "slot_count": 0}
    assert ctrl.snapshot()["slots"]["rows"] == []
    assert "표기로 되돌렸습니다" in ctrl.snapshot()["result"]["text"]
    # 되돌린 템플릿은 다시 PARTIAL 이다 — 「변환 전까지 못 만든다」는 확인 문안의 재확인.
    row = next(r for r in _items(ctrl.snapshot()["hwpx"]) if r["path"] == path)
    assert row["state"] == "partial"


def test_slot_decompile_all_guards_the_same_paths_as_the_row_verbs(tmp_path, monkeypatch):
    """문서 단위 동사도 라이브러리 관문을 지난다(임의 파일 변이 권한 승격 차단)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    foreign = tp / "foreign.hwpx"
    write_hwpx_package(foreign, _pkg(_NOTATION_BODY))
    before = foreign.read_bytes()

    with pytest.raises(ValueError, match="현재 라이브러리 목록에 없는"):
        ctrl.dispatch("slot_decompile_all", {"path": str(foreign)})
    assert foreign.read_bytes() == before


def test_slot_verbs_notify_the_reconciliation_seam(tmp_path, monkeypatch):
    """bytes 변이 동사 넷이 전부 S8G-00 재정산 seam 을 태운다(#320 선례)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    seen: "list[tuple[str, str]]" = []
    ctrl.mutation_sinks.append(lambda kind, mutated: seen.append((kind, mutated)))

    ctrl.dispatch("slot_rename", {"path": path, "slot_id": "특약", "label": "새 이름"})
    ctrl.dispatch("slot_decompile", {"path": path, "slot_id": "특약", "confirm": True})
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("slot_decompile_all", {"path": path, "confirm": True})
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("slot_remove", {"path": path, "slot_id": "특약", "confirm": True})

    assert [kind for kind, _ in seen] == ["mutated"] * 6
    assert {mutated for _, mutated in seen} == {path}


def test_slot_verbs_reject_paths_outside_the_live_library(tmp_path, monkeypatch):
    """라이브러리 밖 임의 파일 변이 권한 승격 차단(_do_delete 와 같은 술어)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    foreign = tp / "foreign.hwpx"
    write_hwpx_package(foreign, _pkg(_NOTATION_BODY))
    before = foreign.read_bytes()

    for action in ("slot_rename", "slot_decompile", "slot_remove"):
        with pytest.raises(ValueError, match="현재 라이브러리 목록에 없는"):
            ctrl.dispatch(action, {"path": str(foreign), "slot_id": "특약"})
    assert foreign.read_bytes() == before

    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    with pytest.raises(ValueError, match="항목 id 가 비어"):
        ctrl.dispatch("slot_rename", {"path": path, "slot_id": "  ", "label": "x"})


def test_slot_list_is_dropped_when_its_template_disappears(tmp_path, monkeypatch):
    """목록이 죽은 경로를 겨눈 채 남지 않는다(누를 때야 실패하는 버튼 금지)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    assert ctrl.snapshot()["slots"] is not None

    # 삭제 동사는 U6-A 에서 퇴역했다 — 파일이 사라지는 길은 이제 탐색기(밖)뿐이고,
    # 목록이 그 부재를 스스로 알아채는 것이 이 계약이다.
    Path(path).unlink()
    ctrl.dispatch("refresh", {})

    assert ctrl.snapshot()["slots"] is None


# ================================================================ TXT 저작
def test_txt_new_and_edit_roundtrip(tmp_path, monkeypatch):
    """새 TXT → 편집. **삭제 동사는 없다**(U6-A) — 앱은 사용자 서식 폴더에 쓰지 않는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("txt_new", {"name": "회의결과", "content": "{{안건}}"})
    assert (tp / "lib" / "회의결과.txt").read_text(encoding="utf-8") == "{{안건}}"
    ctrl.dispatch("txt_edit", {
        "path": str(tp / "lib" / "회의결과.txt"), "content": "{{안건}} {{일시}}",
        "baseline": "{{안건}}",           # 드리프트 없음(= 연 그대로) → 즉시 쓰기
    })
    assert (tp / "lib" / "회의결과.txt").read_text(encoding="utf-8") == "{{안건}} {{일시}}"


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
        ctrl.dispatch("txt_edit", {
            "path": str(foreign), "content": "changed", "baseline": "do not touch"
        })
    with pytest.raises(ValueError, match="현재 TXT 라이브러리"):
        ctrl.dispatch("txt_content", {"path": str(foreign)})
    assert foreign.read_text(encoding="utf-8") == "do not touch"

    alias = tp / "lib" / "별칭.txt"
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
        ctrl.dispatch("txt_edit", {
            "path": str(alias), "content": "changed", "baseline": "link placeholder"
        })
    assert foreign.read_text(encoding="utf-8") == "do not touch"


# ------------------------------------------- 편집 중 외부 변경(S10G-00 #857 · #216 이월 2)
def _txt_seed(ctrl, tp: Path, content: str = "{{안건}}") -> Path:
    ctrl.dispatch("txt_new", {"name": "회의결과", "content": content})
    return tp / "lib" / "회의결과.txt"


def test_txt_edit_refuses_to_overwrite_an_outside_change_without_confirmation(tmp_path, monkeypatch):
    """편집 창이 열린 사이 파일이 밖에서 바뀌었으면 조용히 덮지 않는다(확인 승격)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _txt_seed(ctrl, tp)
    path.write_text("밖에서 바뀐 내용", encoding="utf-8")  # 창이 열린 사이의 외부 변경

    result = ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}"
    })

    assert result["needs_confirm"] is True and result["kind"] == "txt_drift"
    assert "회의결과" in result["text"] and "외부 변경" in result["text"]
    assert result["fingerprint"]
    assert path.read_text(encoding="utf-8") == "밖에서 바뀐 내용"  # 무변형


def test_txt_edit_writes_after_the_current_state_is_confirmed(tmp_path, monkeypatch):
    """사용자가 그 상태를 보고 확정하면(지문 일치) 덮어쓴다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _txt_seed(ctrl, tp)
    path.write_text("밖에서 바뀐 내용", encoding="utf-8")
    gate = ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}"
    })

    done = ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}",
        "confirm_fingerprint": gate["fingerprint"],
    })

    assert done == {"ok": True}
    assert path.read_text(encoding="utf-8") == "창에서 쓴 내용"


def test_txt_edit_asks_again_when_the_file_changes_between_confirm_and_save(tmp_path, monkeypatch):
    """확인과 저장 사이에 또 바뀌면 낡은 지문은 통하지 않는다 — 새 지문으로 다시 묻는다.

    사용자가 읽고 확정한 문안과 실제로 덮이는 상태가 갈라지지 않게 하는 것이 이 왕복의 전부다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _txt_seed(ctrl, tp)
    path.write_text("1차 외부 변경", encoding="utf-8")
    stale = ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}"
    })
    path.write_text("2차 외부 변경", encoding="utf-8")  # 확인~저장 사이의 또 한 번

    again = ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}",
        "confirm_fingerprint": stale["fingerprint"],
    })

    assert again["needs_confirm"] is True and again["kind"] == "txt_drift"
    assert again["fingerprint"] != stale["fingerprint"]
    assert path.read_text(encoding="utf-8") == "2차 외부 변경"  # 무변형
    # 새 지문으로 확정하면 그제야 쓴다.
    ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}",
        "confirm_fingerprint": again["fingerprint"],
    })
    assert path.read_text(encoding="utf-8") == "창에서 쓴 내용"


def test_txt_edit_drift_gate_does_not_notify_the_editing_session(tmp_path, monkeypatch):
    """쓰지 않은 왕복은 변이가 아니다 — 재정산 통지도 결과 줄도 나가지 않는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _txt_seed(ctrl, tp)
    path.write_text("밖에서 바뀐 내용", encoding="utf-8")
    seen: "list[tuple[str, str]]" = []
    ctrl.mutation_sinks.append(lambda kind, mutated: seen.append((kind, mutated)))

    ctrl.dispatch("txt_edit", {
        "path": str(path), "content": "창에서 쓴 내용", "baseline": "{{안건}}"
    })

    assert seen == []
    assert "저장했습니다" not in ctrl.snapshot()["result"]["text"]


def test_orphan_group_returns_to_ungrouped_after_delete(tmp_path, monkeypatch):
    """Explorer 삭제/이동으로 키가 사라진 지정은 고아 → reconcile 설정 정리(결정 8).

    그룹 표면은 U4 §2-30 에서 걷혔지만 이 위생은 남는다 — 되살릴 때 스캔과 어긋난 지정이
    굳어 있으면 그것이 곧 부채다. 그래서 스냅샷은 여전히 ``reconcile`` 을 돌린다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.hwpx_groups.set_group("raw.hwpx", "입찰")
    (tp / "lib" / "raw.hwpx").unlink()  # 파일이 사라짐
    ctrl.dispatch("refresh", {})
    ctrl.snapshot()
    assert ctrl.hwpx_groups.existing_groups() == []
    assert settings.load_template_group_map("hwpx") == {}  # reconcile 이 유령 지정 정리


def test_import_routes_by_extension_and_is_independent(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    src_txt = ext / "협조전.txt"
    src_txt.write_text("원본", encoding="utf-8")
    _write_compiled(ext / "용역.hwpx")

    # 반환 = 사본의 **전체 경로**(F8 판정 C — 편집기 채택 판정이 정확한 목적지를 안다).
    assert ctrl.import_into_library(str(src_txt)) == str(tp / "lib" / "협조전.txt")
    assert ctrl.import_into_library(str(ext / "용역.hwpx")) == str(tp / "lib" / "용역.hwpx")
    # 확장자로 매체 루트 라우팅.
    assert (tp / "lib" / "협조전.txt").exists() and (tp / "lib" / "용역.hwpx").exists()
    # 원본 후속 수정은 라이브러리 사본에 불파급(복사=참조 아님).
    src_txt.write_text("수정됨", encoding="utf-8")
    assert (tp / "lib" / "협조전.txt").read_text(encoding="utf-8") == "원본"
    # 사본은 「그룹 없음」에서 시작.
    snap = ctrl.snapshot()
    assert "group" not in _item(snap["txt"], "협조전")
    assert "group" not in _item(snap["hwpx"], "용역")


def test_import_name_collision_suffixes(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    (ext / "온나라_기안.txt").write_text("다른내용", encoding="utf-8")
    dest = ctrl.import_into_library(str(ext / "온나라_기안.txt"))
    assert Path(dest).name == "온나라_기안 (2).txt"  # 조용한 덮어쓰기 금지(반환=전체 경로)
    assert (tp / "lib" / "온나라_기안.txt").read_text(encoding="utf-8") == "제목: {{공고명}}"


def test_import_bad_extension_is_loud(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ext = tp / "ext"
    ext.mkdir()
    (ext / "x.pdf").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=".hwpx 또는 .txt"):
        ctrl.import_into_library(str(ext / "x.pdf"))


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
    assert not (tp / "lib" / "협조전.txt").exists()  # 반가져오기 잔재 없음


# ==================================== 폴더 일괄 가져오기(#339 · U2 §2.16 narrow)


def test_legacy_trash_subtree_is_not_rediscovered_as_template(tmp_path, monkeypatch):
    """옛 홈의 ``.trash`` 는 **아직 실재한다** — 스캔 제외가 없으면 지웠던 것이 되살아난다.

    U6-A 에서 삭제·휴지통 동사는 퇴역했지만(앱은 사용자 폴더에 ``.trash`` 를 만들지 않는다)
    이미 만들어진 하위트리는 남아 있다. 그것을 걸러내는 것은 두 매체 **모두**의 의무다."""
    from hwpxfiller.domain.template_status import TRASH_DIR_NAME

    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    trash = tp / "lib" / TRASH_DIR_NAME
    trash.mkdir()
    _write_compiled(trash / "0-old-지운서식.hwpx")
    (trash / "0-old-지운기안.txt").write_text("{{옛것}}", encoding="utf-8")

    snap = ctrl.snapshot()
    assert _names(snap["hwpx"]) == {"comp", "raw"}
    assert _names(snap["txt"]) == {"온나라_기안"}


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
        "<hp:run><hp:t>V<hp:markpenBegin/><hp:markpenEnd/></hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
    ))
    ctrl.dispatch("refresh", {})

    snap = ctrl.snapshot()
    warns = _item(snap["hwpx"], "marker")["fill_warns"]
    assert len(warns) == 1 and "markpenBegin" in warns[0]
    assert _item(snap["hwpx"], "comp")["fill_warns"] == []


# (고지 ②(휘발 「기안」 폐지 재진술) 테스트 삭제 — 문안이 tpl 화면과 함께 사망(F8
#  §10.17). 고지 ①(job txt_note)은 test_webapp_job 이 계속 진다.)


# ------------------------------------------------ 저작 중 본문 판정(S10-05 #862 · #299 회수)
def test_txt_lint_restates_ring0_diagnostics_and_token_spans(tmp_path, monkeypatch):
    """린트 왕복은 **파일이 아니라 창이 든 문자열**을 보고, 링0 판정을 그대로 싣는다.

    좌표가 두 곳에서 나면(웹이 정규식을 다시 쓰면) sigil 선행 분류가 갈려 같은 토큰이
    한쪽에선 구간 마커, 다른 쪽에선 미치환 누름틀이 된다. 그래서 스팬은 여기서 나온다.
    """
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    content = "제목: {{공고명}}\n{{#항목 사유}}"

    result = ctrl.dispatch("txt_lint", {"content": content})

    assert [d["kind"] for d in result["diagnostics"]] == ["unbalanced_marker"]
    assert "닫는 마커가 없습니다" in result["diagnostics"][0]["message"]
    assert result["summary"] == {"slots": 0, "options": 0, "fields": 1, "markers": 1}
    assert result["spans"] == [
        {"kind": "field", "start": 4, "end": 11, "source": "{{공고명}}"},
        {"kind": "marker", "start": 12, "end": 22, "source": "{{#항목 사유}}"},
    ]
    # 좌표는 원문에 **그대로** 얹힌다 — 이 불변식이 깨지면 강조가 조용히 어긋난다.
    for span in result["spans"]:
        assert content[span["start"]:span["end"]] == span["source"]


def test_txt_lint_on_a_clean_body_is_quiet_and_writes_nothing(tmp_path, monkeypatch):
    """진단 0 · 스팬 정상 · 라이브러리 무변경(읽기 전용 왕복이라는 사실의 얼굴)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    before = sorted(p.name for p in (tp / "lib").iterdir())

    result = ctrl.dispatch("txt_lint", {
        "content": "{{#항목 사유 사유}}\n본문\n{{/항목}}\n값: {{금액}}",
    })

    assert result["diagnostics"] == []
    assert result["summary"]["slots"] == 1 and result["summary"]["fields"] == 1
    assert [s["kind"] for s in result["spans"]] == ["marker", "marker", "field"]
    assert sorted(p.name for p in (tp / "lib").iterdir()) == before


def test_txt_lint_accepts_an_empty_body(tmp_path, monkeypatch):
    """빈 본문은 실패가 아니라 「아직 아무것도 없다」다 — 새 창의 첫 판정이 이것이다."""
    ctrl, _, _ = _controller(tmp_path, monkeypatch)

    result = ctrl.dispatch("txt_lint", {"content": ""})

    assert result["diagnostics"] == []
    assert result["spans"] == []
    assert result["summary"] == {"slots": 0, "options": 0, "fields": 0, "markers": 0}


# ============================================ 서식 폴더 단일 루트(U6-A · #975)
def test_snapshot_carries_the_templates_root_zone(tmp_path, monkeypatch):
    """최상위 `templates_root` 존이 링0 도출을 그대로 싣는다(재조립 금지)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    zone = ctrl.snapshot()["templates_root"]
    assert zone == {
        "directory": str(tp / "lib"),
        "source": "default",
        "source_label": "기본 폴더",
        "notice": "",
    }
    # 두 밴드의 `dir` 도 같은 값이다 — 매체별 루트 축은 사라졌다.
    snap = ctrl.snapshot()
    assert snap["hwpx"]["dir"] == snap["txt"]["dir"] == str(tp / "lib")


def test_set_templates_root_moves_both_bands_in_one_push(tmp_path, monkeypatch):
    """재지정 동사는 **홀더 하나**다 — 한 번의 푸시로 hwpx·txt 목록이 새 루트를 본다."""
    ctrl, tp, pushes = _controller(tmp_path, monkeypatch)
    other = tp / "다른서식"
    other.mkdir()
    _write_compiled(other / "새서식.hwpx")
    (other / "새기안.txt").write_text("{{건명}}", encoding="utf-8")
    pushes.clear()

    result = ctrl.set_templates_root(str(other))

    assert result == {"ok": True, "directory": str(other)}
    assert len(pushes) == 1, "재지정이 한 번의 푸시로 끝나지 않았습니다"
    _screen, snap = pushes[0]
    assert _names(snap["hwpx"]) == {"새서식"}
    assert _names(snap["txt"]) == {"새기안"}
    assert snap["templates_root"]["source_label"] == "설정한 폴더"
    assert settings.load_templates_root() == str(other)   # 영속까지 갔다


def test_a_missing_configured_root_shows_an_empty_list_with_a_reason(tmp_path, monkeypatch):
    """**기본 폴더로 내려가지 않는다** — 빈 목록 + 사유 + empty_hint 로 시끄럽게 선다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    gone = tp / "사라진서식"

    ctrl.set_templates_root(str(gone))

    snap = ctrl.snapshot()
    assert snap["templates_root"]["directory"] == str(gone)   # 옛 루트로 되돌아가지 않는다
    assert "찾을 수 없습니다" in snap["templates_root"]["notice"]
    assert _names(snap["hwpx"]) == set() and _names(snap["txt"]) == set()
    # 빈 목록 문안은 링1 하나가 정본이고 두 밴드가 같은 말을 한다.
    assert snap["hwpx"]["empty_hint"] == snap["txt"]["empty_hint"] == ctrl.vm.empty_hint()
    assert "서식 폴더가 없습니다" in snap["hwpx"]["empty_hint"]


def test_set_templates_root_rejects_empty_and_file_paths_loudly(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    before = ctrl.snapshot()["templates_root"]["directory"]
    with pytest.raises(ValueError, match="비어 있습니다"):
        ctrl.set_templates_root("   ")
    with pytest.raises(ValueError, match="폴더가 아니라 파일"):
        ctrl.set_templates_root(str(tp / "lib" / "raw.hwpx"))
    assert ctrl.snapshot()["templates_root"]["directory"] == before   # 아무것도 안 바뀐다


def test_display_names_follow_the_same_rule_for_both_media(tmp_path, monkeypatch):
    """하위 폴더 항목의 이름은 hwpx·txt 모두 **루트 상대경로·확장자 제외**다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    sub = tp / "lib" / "온나라"
    sub.mkdir()
    _write_compiled(sub / "공고서.hwpx")
    (sub / "기안.txt").write_text("{{건명}}", encoding="utf-8")
    ctrl.dispatch("refresh", {})

    snap = ctrl.snapshot()
    assert "온나라/공고서" in _names(snap["hwpx"])
    assert "온나라/기안" in _names(snap["txt"])


def test_retired_verbs_are_refused_by_the_action_registry():
    """퇴역 액션은 registry 검증에서 거절된다 — 표면 없는 통로를 남기지 않는다."""
    from hwpxfiller.webapp.action_registry import validate_dispatch

    for action in ("delete", "undo_delete", "scan_import_folder", "import_folder"):
        with pytest.raises(ValueError):
            validate_dispatch("tpl", action, {})


def test_migration_restatement_rides_the_templates_root_notice(tmp_path, monkeypatch):
    """이관 재진술은 **화면에 닿는다**(U6-A 리뷰) — 로그만 두면 사용자는 영영 모른다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch, migration_notice="TXT 템플릿 2건을 옮겼습니다")
    assert ctrl.snapshot()["templates_root"]["notice"] == "TXT 템플릿 2건을 옮겼습니다"


def test_a_missing_root_notice_and_the_migration_notice_stand_together(tmp_path, monkeypatch):
    """도출 사유와 이관 재진술은 서로를 지우지 않는다 — 하나가 덮으면 조용한 소실이다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch, migration_notice="옮겼습니다")
    ctrl.set_templates_root(str(tp / "사라진서식"))

    notice = ctrl.snapshot()["templates_root"]["notice"]
    assert "찾을 수 없습니다" in notice and "옮겼습니다" in notice
    assert notice.splitlines() == [notice.splitlines()[0], "옮겼습니다"]


def test_no_migration_leaves_the_notice_untouched(tmp_path, monkeypatch):
    """이관이 없었으면 사유도 없다 — 빈 문자열을 줄바꿈으로 실어 빈 줄을 만들지 않는다."""
    ctrl, _tp, _ = _controller(tmp_path, monkeypatch)
    assert ctrl.snapshot()["templates_root"]["notice"] == ""
