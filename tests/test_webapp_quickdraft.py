"""빠른 기안 컨트롤러 골격 가드 — R-flow 블록 5, #90 슬라이스 7 PR-1(헤드리스).

빠른 기안 = 작업의 휘발 쌍둥이(결정 29). PR-1 은 도달 가능한 빈손 화면만 세운다 —
컨트롤러가 링1 :class:`~hwpxfiller.gui.quickdraft_state.QuickDraftViewModel` 을 소유해
빈 세션 스냅샷·템플릿 목록을 창 없이 내는지, 미지 액션을 시끄럽게 거부하는지, 브리지에
등록됐는지를 본다. 템플릿 소스(PR-2)·데이터 결속(PR-3)·복사/가드(PR-4)는 각 PR 에서 심는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_quickdraft import QuickDraftController


def _controller(tmp_path: Path) -> "tuple[QuickDraftController, list]":
    (tmp_path / "개찰참관보고.txt").write_text(
        "제목: {{사업명}} 개찰 참관 보고\n금액: {{추정가격}}", encoding="utf-8"
    )
    pushes: list = []
    ctrl = QuickDraftController(
        TextTemplateRegistry(tmp_path),
        lambda s, snap: pushes.append((s, snap)),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
    )
    return ctrl, pushes


def test_name_is_quickdraft(tmp_path):
    ctrl, _ = _controller(tmp_path)
    assert ctrl.name == "quickdraft"


def test_initial_lists_templates_and_merges_snapshot(tmp_path):
    """initial = 슬롯 드롭다운용 라이브러리 목록 + 빈 세션 스냅샷(txt/job 관례)."""
    ctrl, _ = _controller(tmp_path)
    init = ctrl.initial()
    assert init["templates"] == ["개찰참관보고"]
    # 스냅샷 키가 병합돼 있어야 한다(웹이 initial 1회로 첫 렌더).
    assert init["origin"] is None
    assert init["template_text"] == ""
    assert init["tokens"] == []
    assert init["has_data"] is False


def test_snapshot_empty_session_shape(tmp_path):
    """빈 세션 = 휘발 그릇 초기 형상. 없는 걸 있는 척하지 않는다(confirm-or-alarm)."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert snap == {
        "origin": None,
        "template_name": None,
        "template_text": "",
        "modified": False,
        "tokens": [],
        "segments": [],
        "missing_fields": [],
        "empty_fields": [],
        "unfilled_count": 0,
        "has_data": False,
        "data_label": "",
        "data_kind": "",
    }


def test_dispatch_unknown_action_raises(tmp_path):
    """미지 액션은 조용히 무시하지 않고 시끄럽게 거부(P5 규약 정렬)."""
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("nope", {})


# ------------------------------------------------------------- 템플릿 소스(PR-2)

def test_select_template_is_session_copy_with_tokens(tmp_path):
    """라이브러리 선택 = 세션 사본(origin=lib·modified=False) + 토큰 파싱(파이프라인 폼)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    snap = pushes[-1][1]
    assert snap["origin"] == "lib" and snap["template_name"] == "개찰참관보고"
    assert snap["modified"] is False
    assert [t["name"] for t in snap["tokens"]] == ["사업명", "추정가격"]
    # 아직 값이 없으니 전부 missing({{토큰}}) — 미채움 = 토큰 수.
    assert snap["missing_fields"] == ["사업명", "추정가격"]
    assert snap["unfilled_count"] == 2
    assert all(t["state"] == "blank" for t in snap["tokens"])


def test_paste_template_has_no_name(tmp_path):
    """붙여넣기 = 이름 없는 세션 사본(라이브러리 비저장)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("paste_template", {"text": "제목: {{공고명}}"})
    snap = pushes[-1][1]
    assert snap["origin"] == "paste" and snap["template_name"] is None
    assert [t["name"] for t in snap["tokens"]] == ["공고명"]


def test_typing_actions_return_snapshot_without_pushing(tmp_path):
    """타이핑 액션(set_token·edit_source)은 푸시하지 않고 스냅샷을 반환한다 — 포커스 입력
    보호(_NO_PUSH): 서버 푸시가 재렌더로 포커스된 textarea 를 뭉개면 왕복 중 글자 유실·IME
    조합 중단(슬라이스 4 경합). JS 는 반환 스냅샷으로 겨냥 패치한다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    n = len(pushes)
    r1 = ctrl.dispatch("set_token", {"name": "사업명", "text": "행정정보시스템"})
    r2 = ctrl.dispatch("edit_source", {"text": "제목: {{사업명}}"})
    assert len(pushes) == n, "타이핑 액션이 푸시했습니다 — 포커스 입력 재구성 위험(_NO_PUSH 위반)."
    assert isinstance(r1, dict) and isinstance(r2, dict), "타이핑 액션이 스냅샷을 반환하지 않습니다."


def test_set_token_fills_preview_and_state(tmp_path):
    """수기 값 입력 → 채움 표지(fill) + 칩 man + 미채움 감소. 빈 값은 missing 유지."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    snap = ctrl.dispatch("set_token", {"name": "사업명", "text": "행정정보시스템 유지보수"})
    kinds = {s.get("name"): s["kind"] for s in snap["segments"] if s["kind"] != "literal"}
    assert kinds["사업명"] == "fill" and kinds["추정가격"] == "missing"
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["사업명"]["state"] == "man" and by_name["사업명"]["value"] == "행정정보시스템 유지보수"
    assert by_name["추정가격"]["state"] == "blank"
    assert snap["unfilled_count"] == 1


def test_edit_source_live_retokenizes_and_demotes(tmp_path):
    """원문 라이브 편집 → 토큰 재구성 + 라이브러리 유래 (수정됨) 강등(동명 값 승계)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    ctrl.dispatch("set_token", {"name": "사업명", "text": "행정정보시스템"})
    # 원문에 새 토큰을 추가 — 동명 토큰(사업명) 값은 살고, 새 토큰(수요기관)만 초기화.
    snap = ctrl.dispatch("edit_source", {"text": "제목: {{사업명}} · {{수요기관}}"})
    assert snap["modified"] is True
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["사업명"]["value"] == "행정정보시스템"  # 승계
    assert by_name["수요기관"]["state"] == "blank"  # 신규
    assert "추정가격" not in by_name  # 사라진 토큰은 버려짐


def test_empty_paste_clears_to_empty_session(tmp_path):
    """빈 붙여넣기(공백뿐) = 빈 세션 — origin='paste' 로 두면 슬롯·본문·알약이 어긋난다(리뷰 확정)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    ctrl.dispatch("paste_template", {"text": "   \n  "})
    snap = pushes[-1][1]
    assert snap["origin"] is None and snap["template_text"] == ""
    assert snap["tokens"] == []


def test_clipboard_text_keeps_unfilled_token_literal(tmp_path):
    """복사 평문 불변식 — 세그먼트 텍스트 연결 = 채운 값 + 미채움 {{토큰}} 원문(render_record 동형)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    snap = ctrl.dispatch("set_token", {"name": "사업명", "text": "행정정보시스템"})
    plain = "".join(s["text"] for s in snap["segments"])
    assert plain == "제목: 행정정보시스템 개찰 참관 보고\n금액: {{추정가격}}"


def test_registered_in_frontend(tmp_path, monkeypatch):
    """브리지가 빠른 기안 컨트롤러를 등록하고 initial 로 라우팅한다(등록 한 줄 결선 확인)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    assert "quickdraft" in frontend.controllers
    init = frontend.initial("quickdraft")
    assert "templates" in init and init["origin"] is None
