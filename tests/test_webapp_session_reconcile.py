"""템플릿 bytes 변이 → 편집 세션 재정산 계약 가드(S8G-00 #320) — 헤드리스.

tpl 채널이 파일을 **제자리에서** 바꾸거나(누름틀 변환·TXT 내용 저장) 치우거나(휴지통 이동)
되돌리는 동안, 같은 파일을 든 편집 세션은 종전에 아무것도 몰랐다: 스키마는 로드 시점 그대로
얼어붙고, 삭제된 템플릿을 가리키는 작업이 조용히 저장됐다. 여기서 재는 것은 그 재정산이다.

**실 조립을 쓴다**: 배선(`app.py` 의 사후 주입 한 줄)이 빠지면 컨트롤러 단위 테스트는 전부
초록인 채 제품만 조용히 낡는다 — 그래서 :class:`~hwpxfiller.webapp.app.WebFrontend` 를 그대로
세우고 tpl 액션을 dispatch 해 편집 세션의 스냅샷을 되읽는다(창 없이 구동된다).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.host.locations import default_templates_dir
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

#: 세션 저장 게이트가 요구하는 데이터 결속의 재료(#932 U4-C) — 매핑 판정은 안 바꾼다.
MULTI_SHEET = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
_TOKEN_BODY = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"


def _frontend(tmp_path: Path):
    """실 브리지 조립 — 홈은 conftest autouse 가 이미 tmp 로 못박았다."""
    from hwpxfiller.webapp import app as app_mod

    # U6-A(#975): 서식 폴더는 지정 없으면 앱 홈 ``templates`` 하나이고 두 매체가 공유한다.
    default_templates_dir().mkdir(parents=True, exist_ok=True)
    return app_mod.WebFrontend()


def _txt(frontend, name: str, body: str) -> Path:
    """TXT 템플릿 하나를 tpl 채널의 정규 동사로 만든다(레지스트리 목록에 실재해야 한다)."""
    frontend.controllers["tpl"].dispatch("txt_new", {"name": name, "content": body})
    return frontend.controllers["tpl"].text_registry.directory / f"{name}.txt"


def _txt_edit(frontend, path: Path, body: str):
    """TXT 내용 저장 — 편집 창이 연 원문을 ``baseline`` 으로 싣는다(드리프트 없음 · #857)."""
    return frontend.controllers["tpl"].dispatch(
        "txt_edit",
        {"path": str(path), "content": body, "baseline": path.read_text(encoding="utf-8")},
    )


def _raw_hwpx(name: str = "계약서") -> Path:
    """평문 ``{{토큰}}`` 만 든 미컴파일 HWPX 를 라이브러리 루트에 놓는다(compile 대상)."""
    sec = (f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{_TOKEN_BODY}</hs:sec>').encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    path = default_templates_dir() / f"{name}.hwpx"
    write_hwpx_package(path, pkg)
    return path


def _mounted_txt_session(frontend, path: Path):
    """TXT 세션 하나를 매핑까지 세운다 — 첫 토큰은 상수로 **확정**해 둔다(이월 관측점).

    데이터도 연결해 둔다: 저장 게이트가 결속을 요구하므로(#932 U4-C S2-3) 안 세우면 이
    파일의 저장 단언이 전부 **데이터 게이트**에 막혀, 정작 재려던 템플릿 소실 차단이
    도달하지 않는다(앞선 술어가 뒤의 술어를 가린다).
    """
    editor = frontend.controllers["editor"]
    editor.load_template_path(str(path))
    editor.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    editor.dispatch("goto_section", {"section": "binding"})
    editor.dispatch("set_display", {"index": 0, "type": "const", "fmt": ""})
    editor.dispatch("set_const", {"index": 0, "const": "총무과"})
    for row in editor.snapshot()["rows"]:
        # 전 행 확인 — 내용 행은 배지, 빈 행은 「비워 둠」(U6-C #977: 「모두 확정」 2발의 후계).
        if row["confirmable"]:
            editor.dispatch("set_confirmed", {"index": row["index"], "confirmed": True})
        else:
            editor.dispatch("set_blank", {"index": row["index"]})
    return editor


def _field_names(editor) -> "list[str]":
    return [f.name for f in editor.schema.fields] if editor.schema else []


def _row(editor, field: str) -> dict:
    return next(r for r in editor.snapshot()["rows"] if r["template_field"] == field)


# ==================================================== ① 제자리 변경(#320 시나리오 1)
def test_txt_edit_reruns_the_live_editor_session_schema_and_mapping(tmp_path):
    """TXT 원문에 토큰이 늘면 세션 스키마·매핑이 그 자리에서 다시 선다(warn 재진술).

    종전에는 세션이 로드 시점 토큰만 알아, 새로 넣은 토큰이 매핑표에 **영영** 안 떴다.
    """
    fe = _frontend(tmp_path)
    path = _txt(fe, "기안", "수신: {{수신}}\n제목: {{제목}}")
    editor = _mounted_txt_session(fe, path)
    assert _field_names(editor) == ["수신", "제목"]
    assert _row(editor, "수신")["confirmed"] is True

    _txt_edit(fe, path, "수신: {{수신}}\n제목: {{제목}}\n담당: {{담당}}")

    assert _field_names(editor) == ["수신", "제목", "담당"]
    snap = editor.snapshot()
    assert [r["template_field"] for r in snap["rows"]] == ["수신", "제목", "담당"]
    # 이월은 값만 — 확정은 전원 해제된다(_ensure_model 의 기존 의미론 그대로).
    assert _row(editor, "수신")["const"] == "총무과"
    assert _row(editor, "수신")["confirmed"] is False
    assert snap["is_complete"] is False
    assert snap["notice"]["level"] == "warn"
    assert "다시 읽었습니다" in snap["notice"]["text"]
    assert "다시 확정" in snap["notice"]["text"]  # 이월 재진술을 덮어쓰지 않는다


# ==================================================== ② 삭제 → danger + 저장 차단
def test_delete_marks_the_session_danger_and_blocks_save_loudly(tmp_path):
    fe = _frontend(tmp_path)
    path = _txt(fe, "기안", "수신: {{수신}}")
    editor = _mounted_txt_session(fe, path)
    editor.dispatch("set_name", {"name": "발주 기안"})
    assert editor.snapshot()["is_complete"] is True

    # 앱 안의 삭제 동사는 U6-A 에서 퇴역했다 — 파일이 사라지는 길은 탐색기(밖)와 동결
    # 온보딩의 예제 제거뿐이고, 둘 다 같은 `deleted` 통지로 이 세션에 닿는다.
    path.unlink()
    fe.controllers["tpl"]._notify_mutation("deleted", str(path))

    notice = editor.snapshot()["notice"]
    assert notice["level"] == "danger" and "삭제됐습니다" in notice["text"]
    # 복원 왕복이 닿을 자리는 남긴다 — 경로를 비우면 되돌리기가 세션을 못 살린다.
    assert editor.template_path == str(path)

    result = editor.dispatch("save", {})
    assert result["ok"] is False
    assert "템플릿 파일이 없어 저장하지 않았습니다" in result["block_reason"]
    assert editor.registry.exists("발주 기안") is False


# ==================================================== ③ 복원 왕복


def test_compile_apply_reruns_the_session_schema(tmp_path):
    """평문 토큰 hwpx 를 든 세션이 tpl 변환 확정 뒤 필드를 갖는다(S8 이 얹힐 자리)."""
    fe = _frontend(tmp_path)
    raw = _raw_hwpx()
    fe.controllers["tpl"].dispatch("refresh", {})
    editor = fe.controllers["editor"]
    editor.load_template_path(str(raw))
    assert editor.schema is None and editor.snapshot()["raw_block"]  # RAW = 채울 대상 0

    fe.controllers["tpl"].dispatch("compile", {"path": str(raw), "confirm": True})

    assert _field_names(editor) == ["계약명"]
    snap = editor.snapshot()
    assert snap["raw_block"] == "" and snap["field_count"] == 1
    assert snap["notice"]["level"] == "warn"


# ====================== ④b 변이 여부에 결속된 통지(S8-F2 · #853 F-3·F-4)
def _bookmark_p(begin_id: str, name: str, value: str) -> str:
    return (
        f'<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="{begin_id}" type="BOOKMARK" '
        f'name="{name}"/></hp:ctrl><hp:t>{value}</hp:t>'
        f'<hp:ctrl><hp:fieldEnd beginIDRef="{begin_id}"/></hp:ctrl></hp:run></hp:p>'
    )


def _collision_hwpx(name: str = "충돌") -> Path:
    """평문 토큰 0 + 이름이 겹치는 기존 책갈피 → 구간 거절이 서지만 **변이는 0** 인 문서."""
    body = (
        _bookmark_p("5", "특약", "남의 구간")
        + "".join(
            f"<hp:p><hp:run><hp:t>{line}</hp:t></hp:run></hp:p>"
            for line in ("{{#항목 특약}}", "본문", "{{/항목}}")
        )
    )
    sec = (f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{body}</hs:sec>').encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    path = default_templates_dir() / f"{name}.hwpx"
    write_hwpx_package(path, pkg)
    return path


def test_field_mutation_notifies_even_when_the_structure_step_raises(tmp_path):
    """필드는 이미 저장됐고 구간 단계가 터진 갈래 — 통지 1회 + 세션 재정산 + danger.

    S8G-00(#320)이 닫은 결함류가 예외 경로에 잔존했다(#853 F-3): bytes 는 이미 바뀌었는데
    통지가 안 서서 같은 파일을 든 편집 세션이 낡은 스키마로 남았다.
    """
    from dataclasses import replace

    fe = _frontend(tmp_path)
    raw = _raw_hwpx()
    fe.controllers["tpl"].dispatch("refresh", {})
    editor = fe.controllers["editor"]
    editor.load_template_path(str(raw))
    assert editor.schema is None  # RAW

    tpl = fe.controllers["tpl"]
    seen: list[tuple[str, str]] = []
    tpl.mutation_sinks.append(lambda kind, path: seen.append((kind, path)))

    def boom(_path: str):
        raise ValueError("구간 커널이 멈췄습니다")

    tpl.vm._file_ops = replace(tpl.vm._file_ops, compile_structure_file=boom)
    tpl.dispatch("compile", {"path": str(raw), "confirm": True})

    assert seen == [("mutated", str(raw))]  # 변이가 있었으니 통지가 선다
    assert _field_names(editor) == ["계약명"]  # 세션이 새 스키마로 다시 섰다
    assert editor.snapshot()["notice"]["level"] == "warn"
    result = tpl.snapshot()["column"]["result"]
    assert result["level"] == "danger"
    assert "구간 커널이 멈췄습니다" in result["text"]


def test_zero_mutation_refusal_notifies_nothing(tmp_path):
    """무변이 거절은 통지 0 · 세션 notice 0 — 안 바뀐 파일로 거짓 경보를 내지 않는다(F-4)."""
    fe = _frontend(tmp_path)
    target = _collision_hwpx()
    tpl = fe.controllers["tpl"]
    tpl.dispatch("refresh", {})
    editor = fe.controllers["editor"]
    editor.load_template_path(str(target))
    before_snapshot = editor.snapshot()
    before_bytes = target.read_bytes()
    seen: list[tuple[str, str]] = []
    tpl.mutation_sinks.append(lambda kind, path: seen.append((kind, path)))

    tpl.dispatch("compile", {"path": str(target), "confirm": True})

    assert seen == []
    assert target.read_bytes() == before_bytes
    # 세션은 손대지 않았다(재정산 notice 없음 · 스키마 그대로). 스냅샷 전체는 tpl 결과 줄을
    # 품고 있어 같을 수 없으므로 세션 소유분만 대조한다.
    after = editor.snapshot()
    assert after["notice"] == before_snapshot["notice"]
    assert after["rows"] == before_snapshot["rows"]
    assert _field_names(editor) == []
    result = tpl.snapshot()["column"]["result"]
    assert result["level"] == "warn" and "구간 변환은 하지 못했습니다" in result["text"]


# ==================================================== ⑤ 남의 파일 변이 = 무변화
def test_mutation_of_another_template_leaves_the_session_untouched(tmp_path):
    fe = _frontend(tmp_path)
    mine = _txt(fe, "기안", "수신: {{수신}}")
    other = _txt(fe, "회의록", "안건: {{안건}}")
    editor = _mounted_txt_session(fe, mine)
    before = editor.snapshot()
    pushes: list = []
    editor._push_sink = lambda screen, snap: pushes.append((screen, snap))

    _txt_edit(fe, other, "안건: {{안건}}\n장소: {{장소}}")
    other.unlink()
    fe.controllers["tpl"]._notify_mutation("deleted", str(other))

    assert editor.snapshot() == before
    assert pushes == []  # 남의 변이는 내 화면을 다시 그리지도 않는다


# ==================================================== ⑥ 배선 존재(실 조립)
def test_app_assembly_wires_tpl_mutations_into_the_editor(tmp_path):
    """조립부의 사후 배선이 실재한다 — 컨트롤러 단위 초록이 제품 배선을 증명하지 않는다."""
    fe = _frontend(tmp_path)
    sinks = fe.controllers["tpl"].mutation_sinks
    assert fe.controllers["editor"].reconcile_template_mutation in sinks


def test_unknown_mutation_kind_is_loud_on_both_sides(tmp_path):
    fe = _frontend(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 템플릿 변이 종류"):
        fe.controllers["tpl"]._notify_mutation("moved", "C:/x.txt")
    with pytest.raises(ValueError, match="알 수 없는 템플릿 변이 종류"):
        fe.controllers["editor"].reconcile_template_mutation("moved", "C:/x.txt")


def test_sink_failure_is_not_swallowed_by_the_mutating_verb(tmp_path):
    """재정산이 던지면 변이 동사가 그대로 시끄럽다(조용한 미정산 금지)."""
    fe = _frontend(tmp_path)
    path = _txt(fe, "기안", "수신: {{수신}}")

    def explode(kind: str, mutated: str) -> None:
        raise RuntimeError("재정산 실패")

    fe.controllers["tpl"].mutation_sinks.append(explode)
    with pytest.raises(RuntimeError, match="재정산 실패"):
        _txt_edit(fe, path, "{{수신}}")


# ==================================================== ⑦ RAW 강등 — 낡은 모델 생존 금지
def test_raw_downgrade_drops_the_stale_model_loudly(tmp_path):
    """토큰을 전부 지우면 채울 대상이 0 이다. 낡은 매핑이 살아남으면 저장 게이트가 뚫린다."""
    fe = _frontend(tmp_path)
    path = _txt(fe, "기안", "수신: {{수신}}")
    editor = _mounted_txt_session(fe, path)
    editor.dispatch("set_name", {"name": "발주 기안"})
    assert editor.snapshot()["is_complete"] is True

    _txt_edit(fe, path, "토큰 없는 안내문")

    snap = editor.snapshot()
    assert editor.model is None and editor.schema is None
    assert snap["rows"] == [] and snap["is_complete"] is False
    assert snap["raw_block"]
    assert snap["notice"]["level"] == "danger"
    assert "채울 항목이 없어졌습니다" in snap["notice"]["text"]
    assert editor.dispatch("save", {})["ok"] is False
