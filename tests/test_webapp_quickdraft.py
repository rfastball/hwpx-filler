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
    fmt_options = snap.pop("fmt_options")  # 유형별 프리셋 표는 아래 별도 가드가 본다
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
        "data_source_label": "",
        "columns": [],
        "record_count": 0,
        "row_idx": 0,
        "row_label": "",
    }
    assert set(fmt_options) == {"text", "date", "amount", "const"}


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


# ------------------------------------------- 데이터 겨눔·제스처 결속·표현형(PR-3)

def _csv(tmp_path: Path, name: str = "낙찰현황.csv") -> str:
    """열 이름이 토큰과 정확히 같은 열·근사 열·금액 열을 섞은 2행 데이터."""
    p = tmp_path / name
    p.write_text(
        "사업명,추정가격,수요기관명\n행정정보시스템,1234000,조달청\n통합관제,9900,서울시\n",
        encoding="utf-8-sig",
    )
    return str(p)


def _aimed(tmp_path) -> "tuple[QuickDraftController, list]":
    ctrl, pushes = _controller(tmp_path)
    (tmp_path / "기안.txt").write_text(
        "{{사업명}} / {{추정가격}} / {{수요기관}}", encoding="utf-8"
    )
    ctrl.dispatch("select_template", {"name": "기안"})
    ctrl.load_data_path(_csv(tmp_path))
    return ctrl, pushes


def test_load_data_path_aims_and_pushes(tmp_path):
    """임의 파일 겨눔(결정 34) — 브리지 경로라 스스로 푸시하고, 라벨은 K8 합성 단일 출처."""
    ctrl, pushes = _aimed(tmp_path)
    snap = pushes[-1][1]
    assert snap["has_data"] is True and snap["data_kind"] == "file"
    assert snap["data_source_label"] == "파일: 낙찰현황.csv"
    assert snap["columns"] == ["사업명", "추정가격", "수요기관명"]
    assert snap["record_count"] == 2 and snap["row_idx"] == 0
    assert snap["row_label"]  # 식별 요약 열 값 병기(행 스테퍼 재진술)


def test_load_data_path_empty_is_loud_and_leaves_state(tmp_path):
    """0행 파일은 시끄럽게 실패하고 세션은 불변 — 빈 데이터로 갈아엎지 않는다(단일 문구)."""
    ctrl, _ = _controller(tmp_path)
    empty = tmp_path / "빈.csv"
    empty.write_text("사업명,추정가격\n", encoding="utf-8-sig")
    with pytest.raises(ValueError) as exc:
        ctrl.load_data_path(str(empty))
    assert "행이 없습니다" in str(exc.value)
    assert ctrl.snapshot()["has_data"] is False


def test_exact_match_autobinds_near_match_only_suggests(tmp_path):
    """결속 규칙(결정 30): 정확 일치=자동 · 근사=자동 금지 + 보이는 제안."""
    ctrl, pushes = _aimed(tmp_path)
    by_name = {t["name"]: t for t in pushes[-1][1]["tokens"]}
    assert by_name["사업명"]["col"] == "사업명" and by_name["사업명"]["state"] == "auto"
    assert by_name["사업명"]["value"] == "행정정보시스템"
    # 「수요기관」 ⊄ 열 이름 정확 일치 — 자동 결속 금지, 제안만 뜬다(자모 부분일치 재사용).
    assert by_name["수요기관"]["col"] == ""
    assert by_name["수요기관"]["suggest"] == "수요기관명"
    assert by_name["수요기관"]["state"] == "blank"


def test_autobind_respects_hand_typed_value(tmp_path):
    """수기 텍스트 존중 — 사람이 이미 친 값은 자동 결속이 덮지 않는다(조용한 소실 금지)."""
    ctrl, pushes = _controller(tmp_path)
    (tmp_path / "기안.txt").write_text("{{사업명}}", encoding="utf-8")
    ctrl.dispatch("select_template", {"name": "기안"})
    ctrl.dispatch("set_token", {"name": "사업명", "text": "손으로 친 값"})
    ctrl.load_data_path(_csv(tmp_path))
    t = pushes[-1][1]["tokens"][0]
    assert t["col"] == "" and t["value"] == "손으로 친 값"


def test_suggestion_one_click_binds_with_sniffed_format(tmp_path):
    """제안 원클릭 = set_source — 결속 시 표현형 1층(열 유형 자동 추측)이 함께 깔린다."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": "수요기관명"})
    by_name = {t["name"]: t for t in pushes[-1][1]["tokens"]}
    assert by_name["수요기관"]["col"] == "수요기관명" and by_name["수요기관"]["value"] == "조달청"
    # 금액 열은 스니핑이 amount 로 승격 → 기본 프리셋이 「1,234,000원」을 낸다(보이는 추측).
    assert by_name["추정가격"]["fmt_kind"] == "amount"
    assert by_name["추정가격"]["value"] == "1,234,000원"


def test_set_fmt_corrects_expression_layer_two(tmp_path):
    """표현형 2층 — 드롭다운 정정은 매핑과 같은 프리셋 코드로 값만 다시 그린다."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("set_fmt", {"name": "추정가격", "code": "{:,}"})
    by_name = {t["name"]: t for t in pushes[-1][1]["tokens"]}
    assert by_name["추정가격"]["value"] == "1,234,000"


def test_direct_edit_demotes_and_revert_restores(tmp_path):
    """표현형 3층 강등과 그 **출구** — 막다른 강등 금지(결정 31)."""
    ctrl, _ = _aimed(tmp_path)
    snap = ctrl.dispatch("set_token", {"name": "사업명", "text": "사람이 고침"})
    t = {x["name"]: x for x in snap["tokens"]}["사업명"]
    assert t["state"] == "hand" and t["col"] == "사업명" and t["value"] == "사람이 고침"
    ctrl.dispatch("revert_token", {"name": "사업명"})
    t = {x["name"]: x for x in ctrl.snapshot()["tokens"]}["사업명"]
    assert t["state"] == "auto" and t["value"] == "행정정보시스템"


def test_set_row_reprojects_bound_and_keeps_human_values(tmp_path):
    """행 재겨눔 3분류(결정 32): 결속·무수정=조용 재생성 · 직접 수정·수기=유지(혼합)."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("set_token", {"name": "추정가격", "text": "협의"})  # 결속 값 직접 수정
    ctrl.dispatch("set_token", {"name": "수요기관", "text": "직접 입력"})  # 무결속 수기
    ctrl.dispatch("set_row", {"index": 1})
    snap = pushes[-1][1]
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["사업명"]["value"] == "통합관제"  # 관계에서 재생성
    assert by_name["추정가격"]["value"] == "협의"  # 사람 소유 — 유지(혼합)
    assert by_name["수요기관"]["value"] == "직접 입력"


def test_set_row_out_of_range_is_loud(tmp_path):
    """범위 밖 행은 조용히 자르지 않는다(첫 행 강등 = 조용한 추측)."""
    ctrl, _ = _aimed(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("set_row", {"index": 9})


def test_carry_notice_speaks_only_of_non_regenerating_values(tmp_path):
    """고지는 재생성되지 않는 값만 말한다 — 결속·무수정만 있으면 무장하지 않는다(무의미 확인 금지)."""
    ctrl, _ = _aimed(tmp_path)
    assert ctrl.dispatch("carry_notice", {})["armed"] is False
    ctrl.dispatch("set_token", {"name": "사업명", "text": "고침"})
    g = ctrl.dispatch("carry_notice", {})
    assert g["armed"] is True and g["edited"] == ["사업명"] and "사업명" in g["message"]


def test_carry_notice_is_query_and_does_not_push(tmp_path):
    """고지 질의는 무변이 — 재렌더를 유발하면 확인 창을 띄우는 사이 화면이 요동친다."""
    ctrl, pushes = _aimed(tmp_path)
    n = len(pushes)
    ctrl.dispatch("carry_notice", {})
    assert len(pushes) == n


def test_clear_data_freezes_bound_values_as_plain_text(tmp_path):
    """데이터 해제 = 결속 값 평문 동결(결정 30) — 화면이 곧 산출물이라 값이 증발하면 결과가 증발한다."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": "수요기관명"})
    ctrl.dispatch("clear_data", {})
    snap = pushes[-1][1]
    assert snap["has_data"] is False and snap["data_source_label"] == ""
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["추정가격"]["value"] == "1,234,000원"  # 표현형 적용 후 평문으로 동결
    assert by_name["추정가격"]["state"] == "man" and by_name["추정가격"]["col"] == ""
    assert "".join(s["text"] for s in snap["segments"]).startswith("행정정보시스템 / 1,234,000원")


def test_unbind_one_token_also_freezes(tmp_path):
    """토큰 하나만 손으로 떼어내도 값은 남는다 — 해제와 같은 규율(부분 소실 금지)."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "사업명", "col": ""})
    t = {x["name"]: x for x in pushes[-1][1]["tokens"]}["사업명"]
    assert t["col"] == "" and t["value"] == "행정정보시스템" and t["state"] == "man"


def test_bind_unknown_column_is_loud(tmp_path):
    """데이터에 없는 열 결속은 시끄럽게 거절 — 조용한 무결속 강등 금지."""
    ctrl, _ = _aimed(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("set_source", {"name": "사업명", "col": "없는열"})


def test_bound_empty_cell_renders_blank_not_missing(tmp_path):
    """결속인데 데이터가 빈칸 = blank(〈빈 값〉) · 아직 안 채운 자리 = missing({{토큰}}) — 다른 사실."""
    ctrl, _ = _controller(tmp_path)
    (tmp_path / "기안.txt").write_text("{{사업명}} / {{비고}}", encoding="utf-8")
    ctrl.dispatch("select_template", {"name": "기안"})
    p = tmp_path / "빈칸.csv"
    p.write_text("사업명,비고\n행정정보시스템,\n", encoding="utf-8-sig")
    ctrl.load_data_path(str(p))
    snap = ctrl.snapshot()
    kinds = {s.get("name"): s["kind"] for s in snap["segments"] if s["kind"] != "literal"}
    assert kinds["비고"] == "blank"
    assert {t["name"]: t["state"] for t in snap["tokens"]}["비고"] == "auto"


def test_new_token_from_live_edit_autobinds(tmp_path):
    """원문에 토큰을 더 쓰면 그 자리가 데이터에서 채워진다 — 승계 토큰의 소유권은 불변."""
    ctrl, _ = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": ""})
    snap = ctrl.dispatch("edit_source", {"text": "{{사업명}} / {{수요기관명}}"})
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["수요기관명"]["col"] == "수요기관명" and by_name["수요기관명"]["value"] == "조달청"


def test_registered_in_frontend(tmp_path, monkeypatch):
    """브리지가 빠른 기안 컨트롤러를 등록하고 initial 로 라우팅한다(등록 한 줄 결선 확인)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    assert "quickdraft" in frontend.controllers
    init = frontend.initial("quickdraft")
    assert "templates" in init and init["origin"] is None
