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

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
_TOKEN_BODY = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"


def _frontend(tmp_path: Path):
    """실 브리지 조립 — 홈은 conftest autouse 가 이미 tmp 로 못박았다."""
    from hwpxfiller.webapp import app as app_mod

    txt_dir = tmp_path / "txt"
    txt_dir.mkdir(exist_ok=True)
    default_templates_dir().mkdir(parents=True, exist_ok=True)
    return app_mod.WebFrontend(txt_dir)


def _txt(frontend, name: str, body: str) -> Path:
    """TXT 템플릿 하나를 tpl 채널의 정규 동사로 만든다(레지스트리 목록에 실재해야 한다)."""
    frontend.controllers["tpl"].dispatch("txt_new", {"name": name, "content": body})
    return frontend.controllers["tpl"].text_registry.directory / f"{name}.txt"


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
    """TXT 세션 하나를 매핑까지 세운다 — 첫 토큰은 상수로 **확정**해 둔다(이월 관측점)."""
    editor = frontend.controllers["editor"]
    editor.load_template_path(str(path))
    editor.dispatch("goto_section", {"section": "binding"})
    editor.dispatch("set_type", {"index": 0, "type": "const"})
    editor.dispatch("set_const", {"index": 0, "const": "총무과"})
    blanks = editor.dispatch("confirm_all", {})["blanks"]
    if blanks:
        editor.dispatch("confirm_blanks", {"fields": blanks})
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

    fe.controllers["tpl"].dispatch(
        "txt_edit", {"path": str(path), "content": "수신: {{수신}}\n제목: {{제목}}\n담당: {{담당}}"}
    )

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

    fe.controllers["tpl"].dispatch("delete", {"media": "txt", "path": str(path)})

    notice = editor.snapshot()["notice"]
    assert notice["level"] == "danger" and "삭제됐습니다" in notice["text"]
    # 복원 왕복이 닿을 자리는 남긴다 — 경로를 비우면 되돌리기가 세션을 못 살린다.
    assert editor.template_path == str(path)

    result = editor.dispatch("save", {})
    assert result["ok"] is False
    assert "템플릿 파일이 없어 저장하지 않았습니다" in result["block_reason"]
    assert editor.registry.exists("발주 기안") is False


# ==================================================== ③ 복원 왕복
def test_undo_delete_restores_the_session_schema(tmp_path):
    fe = _frontend(tmp_path)
    path = _txt(fe, "기안", "수신: {{수신}}\n제목: {{제목}}")
    editor = _mounted_txt_session(fe, path)
    tpl = fe.controllers["tpl"]

    tpl.dispatch("delete", {"media": "txt", "path": str(path)})
    assert editor.snapshot()["notice"]["level"] == "danger"

    tpl.dispatch("undo_delete", {})

    assert _field_names(editor) == ["수신", "제목"]
    snap = editor.snapshot()
    assert snap["notice"]["level"] == "warn"
    assert "다시 읽었습니다" in snap["notice"]["text"]
    # 파일이 돌아왔으니 심층 방어 차단도 걷힌다(다른 저장 게이트는 이 테스트 밖).
    assert editor._missing_template_block() == ""


# ==================================================== ④ hwpx 누름틀 변환 양성 대조
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


# ==================================================== ⑤ 남의 파일 변이 = 무변화
def test_mutation_of_another_template_leaves_the_session_untouched(tmp_path):
    fe = _frontend(tmp_path)
    mine = _txt(fe, "기안", "수신: {{수신}}")
    other = _txt(fe, "회의록", "안건: {{안건}}")
    editor = _mounted_txt_session(fe, mine)
    before = editor.snapshot()
    pushes: list = []
    editor._push_sink = lambda screen, snap: pushes.append((screen, snap))

    fe.controllers["tpl"].dispatch(
        "txt_edit", {"path": str(other), "content": "안건: {{안건}}\n장소: {{장소}}"}
    )
    fe.controllers["tpl"].dispatch("delete", {"media": "txt", "path": str(other)})

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
        fe.controllers["tpl"].dispatch("txt_edit", {"path": str(path), "content": "{{수신}}"})


# ==================================================== ⑦ RAW 강등 — 낡은 모델 생존 금지
def test_raw_downgrade_drops_the_stale_model_loudly(tmp_path):
    """토큰을 전부 지우면 채울 대상이 0 이다. 낡은 매핑이 살아남으면 저장 게이트가 뚫린다."""
    fe = _frontend(tmp_path)
    path = _txt(fe, "기안", "수신: {{수신}}")
    editor = _mounted_txt_session(fe, path)
    editor.dispatch("set_name", {"name": "발주 기안"})
    assert editor.snapshot()["is_complete"] is True

    fe.controllers["tpl"].dispatch(
        "txt_edit", {"path": str(path), "content": "토큰 없는 안내문"}
    )

    snap = editor.snapshot()
    assert editor.model is None and editor.schema is None
    assert snap["rows"] == [] and snap["is_complete"] is False
    assert snap["raw_block"]
    assert snap["notice"]["level"] == "danger"
    assert "채울 항목이 없어졌습니다" in snap["notice"]["text"]
    assert editor.dispatch("save", {})["ok"] is False
