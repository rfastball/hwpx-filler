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
from hwpxfiller.gui.compile_badge import TEXT_BADGE_LABEL, TEXT_BADGE_LEVEL
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


def _items(snap: dict) -> "list[dict]":
    """고르기 좌 열의 행 전수 — hwpx 다음 txt 로 **한 목록**이다(`column.rows`).

    옛 매체 밴드(`hwpx`/`txt` 의 `sections[].items[]`)는 웹 소비자 0 으로 걷혔다
    (슬라이스 ⑤). 매체는 구획이 아니라 행이 든 표지(`icon`)가 가른다.
    """
    return snap["column"]["rows"]


def _media(snap: dict, icon: str) -> "list[dict]":
    """그 매체의 행만 — 구획 대신 행 표지로 가른다."""
    return [it for it in _items(snap) if it["icon"] == icon]


def _names(snap: dict, icon: "str | None" = None) -> "set[str]":
    rows = _items(snap) if icon is None else _media(snap, icon)
    return {it["name"] for it in rows}


def _item(snap: dict, name: str) -> dict:
    return next(it for it in _items(snap) if it["name"] == name)


def _result(ctrl: TemplateController) -> dict:
    """결과 줄 — 열의 일부다(목록과 같은 존에서 온다)."""
    return ctrl.snapshot()["column"]["result"]


# ============================================================ 목록·배지·액션
def test_initial_serializes_one_column_and_ring1_actions(tmp_path, monkeypatch):
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    snap = ctrl.initial()
    assert _names(snap, "hwpx") == {"raw", "comp"}
    assert _names(snap, "txt") == {"온나라_기안"}
    assert _item(snap, "온나라_기안")["sub"] == "필드 1개"
    # 개수는 **한 목록**의 것이다(매체별 구획이 없다 — 슬라이스 ⑤).
    assert snap["column"]["count_label"] == "3개"
    # 그룹 표면은 U4 §2-30 에서 동결이고 그 투영도 없다.
    assert "group_names" not in snap and "sections" not in snap
    assert snap["column"]["result"]["text"] == ""
    # 드리프트 UI 미노출(10F2FF98-D) — 스냅샷에 drift 표면이 없다.
    assert "drift" not in snap and not any("drift" in k for k in snap)
    # U6-B(#976): 링2 필터가 사라지고 목록은 **링1 그대로**다 — `preview`·`make_job` 은
    # 소비자 0 이라 링1 에서 사슬째 걷혔다. U6-E(#979)는 `review` 까지 걷었다: 상태 게이트가
    # 드는 것은 **수선 동사**뿐이고, 검토 왕복은 웹이 모든 행에 덧붙이는 「자세히…」가 진다.
    assert [a["key"] for a in _item(snap, "comp")["actions"]] == []
    assert [a["key"] for a in _item(snap, "raw")["actions"]] == ["compile"]
    # 「고를 수 있는가」 + 사유는 행이 진다(고르기 좌 열의 단일 판정 출처).
    assert _item(snap, "comp")["selectable"] is True
    assert _item(snap, "comp")["reason"] == ""
    assert _item(snap, "raw")["selectable"] is False
    assert "누름틀·구간 변환" in _item(snap, "raw")["reason"]
    txt_row = _item(snap, "온나라_기안")
    assert txt_row["selectable"] is True and txt_row["sub"] == "필드 1개"


def test_compile_two_phase_scan_then_apply(tmp_path, monkeypatch):
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    raw = str(tp / "lib" / "raw.hwpx")
    before = (tp / "lib" / "raw.hwpx").read_bytes()
    review = ctrl.dispatch("review", {"path": raw})
    assert review["ok"] is True and "검토" in _result(ctrl)["text"]
    res1 = ctrl.dispatch("compile", {"path": raw})
    # 확인 본문은 두 축을 함께 재진술한다(S8-03) — 「항목 n · 선택 m · 누름틀 k」.
    assert res1["needs_confirm"] is True and "누름틀 1개" in res1["confirm_text"]
    assert (tp / "lib" / "raw.hwpx").read_bytes() == before  # dry-run 무변형
    res2 = ctrl.dispatch("compile", {"path": raw, "confirm": True})
    assert res2["applied"] is True and res2["refused"] is False
    assert _result(ctrl)["level"] == "ok"
    # 상태는 배지가 말한다(링1 `compile_badge` 단일 출처) — 행에 별도 상태 축이 없다.
    assert _item(ctrl.snapshot(), "raw")["badge_label"] == "변환됨"
    res = ctrl.dispatch("compile", {"path": str(tp / "lib" / "comp.hwpx")})
    assert res.get("needs_confirm") is not True and res["applied"] is False
    assert "변환할 토큰과 구간이 없습니다" in _result(ctrl)["text"]


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
    assert "변환할 수 없습니다" in _result(ctrl)["text"]
    assert Path(broken).read_bytes() == before


def test_review_projects_the_detail_zone(tmp_path, monkeypatch):
    """검토가 **항목 상세 한 벌**을 스냅샷에 세운다(U6-E #979 — 판정 재조립 없이 투영 그대로).

    시트가 그릴 것이 한 왕복에서 다 선다: 머리(표시명·상태 배지·경로) · 필드 표 · 구간 항목
    표 · 동사 줄. 두 왕복으로 채우면 그 사이에 갈린 사실이 한 화면에 함께 설 수 있다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})

    assert ctrl.snapshot()["detail"] is None  # 검토 전에는 상세가 서지 않는다
    ctrl.dispatch("review", {"path": path})

    detail = ctrl.snapshot()["detail"]
    assert detail["path"] == path and detail["name"] == "구간"
    assert detail["media"] == "hwpx" and detail["state"] == "compiled"
    assert detail["badge_label"] and detail["error"] == ""
    # 필드 표 — 편집기 스키마 표가 그리던 것과 같은 내용(이름 + 링0 추정 유형).
    assert {f["name"] for f in detail["fields"]} == {"지체상금률", "수요기관"}
    assert detail["field_summary"] == f"필드 {detail['field_count']}개"
    assert all(f["type_hint"] for f in detail["fields"])
    # 동사 줄은 링1 상태 게이트 그대로다 — COMPILED 는 수선할 것이 없으므로 **0** 이고,
    # 시트가 실제로 세우는 동사는 그 아래 구간 항목 표의 것들이다(U6-E #979 리뷰 10).
    assert [a["key"] for a in detail["actions"]] == []
    assert detail["slots"]["rows"] == [
        {"id": "특약", "label": "특약 사항", "option_count": 1, "options": ["지체상금 조항"]}
    ]
    assert detail["slots"]["summary"] == "항목 1개 · 선택 1개"
    assert detail["diagnostics"] == []


def test_review_of_a_txt_item_answers_with_fields_and_no_convert_axis(tmp_path, monkeypatch):
    """TXT 상세는 필드 목록과 판독 사유뿐이다 — 없는 상태·구간 축을 지어내지 않는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = str(tp / "lib" / "온나라_기안.txt")

    ctrl.dispatch("review", {"path": path})

    detail = ctrl.snapshot()["detail"]
    assert detail["media"] == "txt" and detail["state"] == ""
    # 상태 축이 없는 자리에는 **매체 표지**가 선다(고르기 열 공용 ⑤ 리뷰) — 그 어휘의 저자는
    # 링1 `compile_badge` 하나이고, 웹은 `media` 로 다시 판정하지 않는다.
    assert detail["badge_label"] == TEXT_BADGE_LABEL
    assert detail["badge_level"] == TEXT_BADGE_LEVEL
    assert [f["name"] for f in detail["fields"]] == ["공고명"]
    assert detail["slots"] is None and detail["actions"] == []
    assert "검토" in _result(ctrl)["text"]


def test_review_of_a_broken_txt_answers_with_the_reason(tmp_path, monkeypatch):
    """판독 실패 행의 「자세히…」가 답할 것은 **사유 하나**다 — 예외로 새지 않는다.

    그 행에서 ⋮ 가 여는 항목은 「자세히…」뿐이고(내용 편집은 못 읽는 파일에 서지 않는다),
    시트가 보이는 것이 이 사유다. 검토가 던지면 그 자리는 영영 답이 없다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    broken = tp / "lib" / "손상.txt"
    broken.write_bytes("한글".encode("cp949"))
    path = str(broken)

    ctrl.dispatch("review", {"path": path})

    detail = ctrl.snapshot()["detail"]
    assert detail["media"] == "txt" and detail["error"]
    assert detail["fields"] == [] and detail["slots"] is None
    assert detail["field_summary"].startswith("읽기 실패: ")
    assert _result(ctrl)["level"] == "danger"


def test_review_rejects_paths_outside_the_live_library(tmp_path, monkeypatch):
    """상세의 경로가 곧 시트 동사들의 대상이다 — 진입에서 같은 관문을 지난다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    foreign = tp / "foreign.hwpx"
    write_hwpx_package(foreign, _pkg(_TOKEN_BODY))

    with pytest.raises(ValueError, match="현재 라이브러리 목록에 없는"):
        ctrl.dispatch("review", {"path": str(foreign)})
    assert ctrl.snapshot()["detail"] is None


def test_is_live_path_is_the_one_membership_gate(tmp_path, monkeypatch):
    """편집기의 경로 화이트리스트가 위임하는 공개 관문(U6-E #979).

    hwpx 는 **판정 전에 재스캔**한다 — 방금 폴더에 떨어진 파일도, 방금 사라진 파일도 그
    한 호출 안에서 최신으로 답해야 편집기 거절 문구가 실행 가능해진다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    live = str(tp / "lib" / "comp.hwpx")
    assert ctrl.is_live_path("hwpx", live) is True
    assert ctrl.is_live_path("txt", str(tp / "lib" / "온나라_기안.txt")) is True
    assert ctrl.is_live_path("hwpx", str(tp / "foreign.hwpx")) is False

    fresh = tp / "lib" / "새로온.hwpx"
    _write_compiled(fresh)
    assert ctrl.is_live_path("hwpx", str(fresh)) is True, "판정 전 재스캔이 빠졌습니다"
    Path(live).unlink()
    assert ctrl.is_live_path("hwpx", live) is False


def test_slot_rename_is_a_single_round_trip(tmp_path, monkeypatch):
    """개명은 파괴가 아니다 — 확인 없이 바로 적용하고 목록을 다시 투영한다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})

    result = ctrl.dispatch("slot_rename", {"path": path, "slot_id": "특약", "label": "새 이름"})

    assert result == {"ok": True, "slot_count": 1}
    assert ctrl.snapshot()["detail"]["slots"]["rows"][0]["label"] == "새 이름"
    assert "항목 이름을 바꿨습니다" in _result(ctrl)["text"]
    # 빈 label 은 이름을 뗀다.
    ctrl.dispatch("slot_rename", {"path": path, "slot_id": "특약", "label": "  "})
    assert ctrl.snapshot()["detail"]["slots"]["rows"][0]["label"] == ""


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
    assert ctrl.snapshot()["detail"]["slots"]["rows"] == []
    assert "표기로 되돌렸습니다" in _result(ctrl)["text"]

    # 다시 변환한 뒤 삭제 왕복.
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    ask = ctrl.dispatch("slot_remove", {"path": path, "slot_id": "특약"})
    assert ask["needs_confirm"] is True and "사라지는 것:" in ask["confirm_text"]
    ctrl.dispatch("slot_remove", {"path": path, "slot_id": "특약", "confirm": True})
    assert ctrl.snapshot()["detail"]["slots"]["rows"] == []


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
    assert [row["id"] for row in ctrl.snapshot()["detail"]["slots"]["rows"]] == ["특약", "부기"]
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
    assert ctrl.snapshot()["detail"]["slots"]["rows"] == []
    assert "표기로 되돌렸습니다" in _result(ctrl)["text"]
    # 되돌린 템플릿은 다시 PARTIAL 이다 — 「변환 전까지 못 만든다」는 확인 문안의 재확인.
    row = next(r for r in _items(ctrl.snapshot()) if r["path"] == path)
    assert row["badge_label"] == "부분 변환"


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


def test_detail_is_dropped_when_its_template_disappears(tmp_path, monkeypatch):
    """목록이 죽은 경로를 겨눈 채 남지 않는다(누를 때야 실패하는 버튼 금지)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("compile", {"path": path, "confirm": True})
    ctrl.dispatch("review", {"path": path})
    assert ctrl.snapshot()["detail"] is not None

    # 삭제 동사는 U6-A 에서 퇴역했다 — 파일이 사라지는 길은 이제 탐색기(밖)뿐이고,
    # 목록이 그 부재를 스스로 알아채는 것이 이 계약이다.
    Path(path).unlink()
    ctrl.dispatch("refresh", {})

    assert ctrl.snapshot()["detail"] is None


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
    assert "저장했습니다" not in _result(ctrl)["text"]


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
    assert "group" not in _item(snap, "협조전")
    assert "group" not in _item(snap, "용역")


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
    assert _names(snap, "hwpx") == {"comp", "raw"}
    assert _names(snap, "txt") == {"온나라_기안"}


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
    warns = _item(snap, "marker")["warns"]
    assert len(warns) == 1 and "markpenBegin" in warns[0]
    assert _item(snap, "comp")["warns"] == []


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
    # 「어느 폴더를 읽고 있는가」의 자리는 이 존 **하나**다 — 매체별 루트 축도, 목록 안
    # 사본도 없다(슬라이스 ⑤ 에서 옛 밴드의 `dir` 이 함께 걷혔다).
    assert "dir" not in ctrl.snapshot()["column"]


def test_set_templates_root_moves_both_media_in_one_push(tmp_path, monkeypatch):
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
    assert _names(snap, "hwpx") == {"새서식"}
    assert _names(snap, "txt") == {"새기안"}
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
    assert _items(snap) == []
    # 빈 목록 문안은 링1 하나가 정본이고 열이 그 값을 그대로 옮긴다.
    assert snap["column"]["empty_hint"] == ctrl.vm.empty_hint()
    assert "서식 폴더가 없습니다" in snap["column"]["empty_hint"]


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
    assert "온나라/공고서" in _names(snap, "hwpx")
    assert "온나라/기안" in _names(snap, "txt")


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


# ================================ U6-E 리뷰 회수(#989) — 시트의 수명·비용·봉투
def test_review_of_a_corrupt_hwpx_answers_with_the_reason_not_an_exception(
    tmp_path, monkeypatch
):
    """판독 실패는 **봉투 안**에 머문다(리뷰 1).

    ``zipfile.BadZipFile`` 은 ``ValueError`` 가 아니라 dispatch 의 거절 봉투를 벗어난다 —
    그러면 오류 행의 「자세히…」가 영영 시트를 못 연다. 접는 자리는 링1 한 곳이고
    (:meth:`TemplateManagerViewModel.review_view`) 여기서 재는 것은 그 결과다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    broken = tp / "lib" / "깨진.hwpx"
    broken.write_bytes(b"not a hwpx zip!!")
    ctrl.dispatch("refresh", {})

    assert ctrl.dispatch("review", {"path": str(broken)}) == {"ok": True}

    detail = ctrl.snapshot()["detail"]
    assert detail["path"] == str(broken) and detail["error"]
    assert detail["state"] == "" and detail["fields"] == [] and detail["slots"] is None
    assert detail["field_summary"].startswith("읽기 실패: ")
    # 결과 줄도 성공으로 접히지 않는다 — 못 읽었다는 사실이 그 자리에서 재진술된다.
    assert _result(ctrl)["level"] == "danger"


def test_convert_reprojects_the_open_detail(tmp_path, monkeypatch):
    """파일을 바꾼 동사 뒤 시트는 낡지 않는다(리뷰 2).

    변환은 상태·배지·필드·구간 항목을 한꺼번에 바꾼다. 목록만 두고 나오면 열려 있는 시트가
    새 항목 목록 위에 옛 상태 배지를 이고 선다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("review", {"path": path})
    before = ctrl.snapshot()["detail"]
    assert before["state"] == "raw" and before["slots"]["rows"] == []

    ctrl.dispatch("compile", {"path": path, "confirm": True})

    after = ctrl.snapshot()["detail"]
    assert after["state"] == "compiled", "변환 뒤 상태가 시트에 반영되지 않았습니다"
    assert [row["id"] for row in after["slots"]["rows"]] == ["특약"]
    assert [a["key"] for a in after["actions"]] == []      # 수선할 것이 없다(리뷰 10)


def test_txt_edit_reprojects_the_open_detail(tmp_path, monkeypatch):
    """TXT 저장도 같은 후처리를 지난다 — 토큰 집합이 바뀌면 시트의 필드 표도 낡는다."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = str(tp / "lib" / "온나라_기안.txt")
    ctrl.dispatch("review", {"path": path})
    assert [f["name"] for f in ctrl.snapshot()["detail"]["fields"]] == ["공고명"]

    ctrl.dispatch("txt_edit", {
        "path": path, "content": "제목: {{공고명}} / 담당: {{담당자}}",
        "baseline": "제목: {{공고명}}",
    })

    assert [f["name"] for f in ctrl.snapshot()["detail"]["fields"]] == ["공고명", "담당자"]


def test_a_mutation_elsewhere_does_not_swap_the_open_detail(tmp_path, monkeypatch):
    """지금 보고 있는 항목과 무관한 변이는 시트를 갈아 끼우지 않는다(리뷰 2 반대편)."""
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = _notation_template(ctrl, tp)
    ctrl.dispatch("review", {"path": path})

    ctrl.dispatch("compile", {"path": str(tp / "lib" / "raw.hwpx"), "confirm": True})

    assert ctrl.snapshot()["detail"]["path"] == path


def test_a_rejected_path_pushes_the_refreshed_list_first(tmp_path, monkeypatch):
    """「목록을 새로 고쳤으니 다시 고르세요」는 **참말이어야 한다**(리뷰 4).

    목록의 정본이 이 채널이므로 그 push 도 여기서 나가야 좌 열이 사라진 행을 지운다.
    나가지 않으면 사람은 같은 행을 다시 눌러 같은 거절만 받는다.
    """
    ctrl, tp, pushes = _controller(tmp_path, monkeypatch)
    ghost = tp / "lib" / "comp.hwpx"
    ctrl.dispatch("refresh", {})
    pushes.clear()
    ghost.unlink()                                   # 탐색기에서 사라졌다

    assert ctrl.is_live_path("hwpx", str(ghost)) is False

    assert pushes, "거절 전에 갱신된 목록을 밀지 않았습니다"
    names = {row["name"] for row in pushes[-1][1]["column"]["rows"]}
    assert "comp" not in names, f"사라진 행이 그대로 실렸습니다: {names!r}"


def test_the_live_gate_does_not_rescan_on_a_cache_hit(tmp_path, monkeypatch):
    """관문 한 번이 라이브러리 전건 판독을 물어 오지 않는다(리뷰 7).

    무조건 재스캔하면 「자세히…」 한 번이 폴더의 모든 파일을 다시 연다(200개면 200 inspect).
    캐시 적중은 **파일 하나의 존재 검사**로 마무리하고, 재스캔은 부재를 만났을 때만 한다.
    """
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    ctrl.dispatch("refresh", {})
    scans = []
    real = ctrl.vm.refresh
    monkeypatch.setattr(ctrl.vm, "refresh", lambda: (scans.append(1), real())[1])

    assert ctrl.is_live_path("hwpx", str(tp / "lib" / "comp.hwpx")) is True
    assert scans == [], "캐시 적중에서 전체 재스캔을 물었습니다"

    # 목록에 없는 경로에서만 한 번 다시 훑는다 — 방금 들어온 파일을 통과시키는 자리다.
    fresh = _write_compiled(tp / "lib" / "새로온.hwpx")
    assert ctrl.is_live_path("hwpx", str(fresh)) is True
    assert len(scans) == 1


def test_review_opens_the_file_once(tmp_path, monkeypatch):
    """검토 한 왕복이 판독과 lint 로 파일을 **두 번** 열지 않는다(리뷰 7)."""
    import hwpxfiller.external.template_inspection as inspection_module

    opens: "list[str]" = []
    real = inspection_module.read_hwpx_package
    monkeypatch.setattr(
        inspection_module, "read_hwpx_package",
        lambda path, *a, **k: (opens.append(str(path)), real(path, *a, **k))[1],
    )
    ctrl, tp, _ = _controller(tmp_path, monkeypatch)
    path = str(tp / "lib" / "comp.hwpx")
    ctrl.dispatch("refresh", {})
    opens.clear()

    ctrl.dispatch("review", {"path": path})

    assert opens.count(path) == 1, f"같은 파일을 여러 번 열었습니다: {opens!r}"


# ---------------------------- 고르기 좌 열 공용 존(고르기 열 공용 계약 ①)
def test_column_zone_is_one_list_of_hwpx_then_txt_in_the_shared_shape(tmp_path, monkeypatch):
    """좌 열은 hwpx 다음 txt 로 **한 목록**이다 — TXT 는 별도 밴드가 아니라 같은 줄의 pill.

    키 집합의 정본은 `webapp/pool_column.py` 하나이고 우 열(`pool` 채널)이 같은 형으로
    선다. 옛 밴드 키(`hwpx`·`txt`)는 웹 소비자 0 으로 걷혔다(슬라이스 ⑤) — 최상위 존은
    이제 넷뿐이다.
    """
    from hwpxfiller.webapp.pool_column import POOL_ROW_KEYS

    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    snap = ctrl.initial()
    column = snap["column"]
    assert tuple(column) == ("rows", "notices", "empty_hint", "count_label", "result")
    assert [r["icon"] for r in column["rows"]] == ["hwpx", "hwpx", "txt"]
    assert all(tuple(r) == POOL_ROW_KEYS for r in column["rows"])
    assert {r["name"] for r in column["rows"]} == {"raw", "comp", "온나라_기안"}
    assert column["count_label"] == "3개"
    # 결과 줄·빈 상태 문안의 자리는 이 존 안 하나다(같은 사실을 두 곳이 말하지 않는다).
    assert column["empty_hint"] == ctrl.vm.empty_hint()
    assert column["notices"] == []
    # 최상위 존 전수 — 옛 밴드·결과 사슬은 걷혔다(소비자 0).
    assert tuple(snap) == ("column", "templates_root", "detail", "examples")


def test_column_row_carries_the_ring1_verdict_and_the_media_badge(tmp_path, monkeypatch):
    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    rows = {r["name"]: r for r in ctrl.initial()["column"]["rows"]}
    # 변환 전은 숨기지 않고 비활성 + 사유(링1 문안 그대로).
    assert rows["raw"]["reason"] == "누름틀·구간 변환을 해야 고를 수 있습니다."
    assert rows["raw"]["selectable"] is False
    assert [a["key"] for a in rows["raw"]["actions"]] == ["compile"]
    assert rows["comp"]["selectable"] is True and rows["comp"]["reason"] == ""
    # TXT 는 상태 축이 없어 링1 배지가 비어 있다 — 한 목록에 서므로 매체 표지를 단다.
    txt = rows["온나라_기안"]
    assert (txt["badge_label"], txt["badge_level"], txt["icon"]) == ("TXT", "muted", "txt")
    assert txt["actions"] == [] and txt["sub"] == "필드 1개"
    assert txt["selectable"] is True
    # 채움 사전 고지(#154)는 hwpx 행만 드는 축이고 링1 값 그대로다 — 좌 열이 그것을 잃으면
    # 「골라도 되지만 이렇게 된다」가 목록에서 조용히 사라진다.
    ring1 = {r.name: r for r in ctrl.vm.rows()}
    assert rows["raw"]["warns"] == list(ring1["raw"].fill_warns)
    assert txt["warns"] == []


def test_the_row_verdict_is_computed_once_per_row(tmp_path, monkeypatch):
    """행마다 링1 판정은 **한 번**이다 — 두 번 부르면 그 둘이 갈릴 자리가 난다."""
    from hwpxfiller.gui.template_manager_state import TemplateRow

    ctrl, _, _ = _controller(tmp_path, monkeypatch)
    calls: list = []
    original = TemplateRow.select_block_reason

    def counted(self):
        calls.append(self.path)
        return original(self)

    monkeypatch.setattr(TemplateRow, "select_block_reason", counted)
    snap = ctrl.snapshot()
    assert len(calls) == len(snap["column"]["rows"]) == 3
