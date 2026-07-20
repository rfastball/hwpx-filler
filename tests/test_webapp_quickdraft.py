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
        "frozen_notice": "",
        # 대상 글꼴 선언·정렬 린트 합류(#134 부록 B-7 (g)) — 선언은 전역 영속이라 빈 세션에도
        # 실린다(미리보기가 첫 렌더부터 선언을 추종해야 "이대로 복사됩니다"가 참이 된다).
        "target_font": "gulimche",
        "lint": {"proportional": False, "space_run": False, "applied": False, "active": False},
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
    ctrl.dispatch("step_row", {"delta": 1})
    snap = pushes[-1][1]
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["사업명"]["value"] == "통합관제"  # 관계에서 재생성
    assert by_name["추정가격"]["value"] == "협의"  # 사람 소유 — 유지(혼합)
    assert by_name["수요기관"]["value"] == "직접 입력"


def test_set_row_out_of_range_is_loud(tmp_path):
    """번호 지정 재겨눔(스테퍼가 클램프해 부르는 링1 진입점)은 범위 밖을 조용히 자르지 않는다."""
    ctrl, _ = _aimed(tmp_path)
    with pytest.raises(ValueError):
        ctrl.vm.set_row(9)


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


def test_data_swap_freezes_dead_bindings_and_alarms(tmp_path):
    """교체로 열이 없어진 결속은 평문 동결 + 경보(고효율 리뷰 P1).

    그냥 두면 없는 열이 빈 문자열로 읽혀 blank(〈빈 값〉 = 데이터의 빈칸)로 렌더된다 —
    열 자체가 없는데 "빈칸"이라 말하는 그럴싸한 거짓(결정 31의 엄격 유지 대상).
    """
    ctrl, pushes = _aimed(tmp_path)
    other = tmp_path / "다른데이터.csv"
    other.write_text("공고명,금액\n통합관제,500\n", encoding="utf-8-sig")
    ctrl.load_data_path(str(other))
    snap = pushes[-1][1]
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["사업명"]["col"] == "" and by_name["사업명"]["state"] == "man"
    assert by_name["사업명"]["value"] == "행정정보시스템"  # 동결(소실 금지)
    assert "굳었습니다" in snap["frozen_notice"] and "사업명" in snap["frozen_notice"]
    # 세그먼트에 blank(데이터 빈칸)가 섞이지 않는다 — 동결 값은 fill 이다.
    kinds = {s.get("name"): s["kind"] for s in snap["segments"] if s["kind"] != "literal"}
    assert kinds["사업명"] == "fill"


def test_frozen_alarm_heals_when_rebound(tmp_path):
    """낡은 경보는 그 자체로 거짓 — 다시 결속하면 경보가 스스로 사라진다."""
    ctrl, pushes = _aimed(tmp_path)
    other = tmp_path / "다른데이터.csv"
    other.write_text("사업명,금액\n통합관제,500\n", encoding="utf-8-sig")
    ctrl.load_data_path(str(other))  # 「추정가격」·「수요기관」 열 소멸, 「사업명」은 생존
    assert "추정가격" in pushes[-1][1]["frozen_notice"]
    ctrl.dispatch("set_source", {"name": "추정가격", "col": "금액", "confirm": True})
    assert pushes[-1][1]["frozen_notice"] == ""


def test_data_swap_resniffs_kind_of_surviving_binding(tmp_path):
    """살아남은 결속의 열 유형은 새 데이터로 다시 스니핑한다 — 옛 amount 가 눌어붙지 않게."""
    ctrl, pushes = _aimed(tmp_path)
    other = tmp_path / "문자금액.csv"
    other.write_text("사업명,추정가격,수요기관명\n통합관제,협의,서울시\n", encoding="utf-8-sig")
    ctrl.load_data_path(str(other))
    by_name = {t["name"]: t for t in pushes[-1][1]["tokens"]}
    assert by_name["추정가격"]["fmt_kind"] == "text" and by_name["추정가격"]["value"] == "협의"


def test_bind_over_hand_typed_value_asks_first(tmp_path):
    """수기 값 덮어쓰기는 되돌릴 수 없다 — 확인을 받고 나서 실행한다(재진술 확인 후 허용)."""
    ctrl, pushes = _controller(tmp_path)
    (tmp_path / "기안.txt").write_text("{{수요기관}}", encoding="utf-8")
    ctrl.dispatch("select_template", {"name": "기안"})
    ctrl.dispatch("set_token", {"name": "수요기관", "text": "손으로 쓴 값"})
    ctrl.load_data_path(_csv(tmp_path))
    r = ctrl.dispatch("set_source", {"name": "수요기관", "col": "수요기관명"})
    assert r and "손으로 쓴 값" in r["confirm"], "덮어쓸 값을 문안이 인용하지 않습니다."
    t = {x["name"]: x for x in pushes[-1][1]["tokens"]}["수요기관"]
    assert t["value"] == "손으로 쓴 값" and t["col"] == "", "확인 전에 이미 덮어썼습니다."
    ctrl.dispatch("set_source", {"name": "수요기관", "col": "수요기관명", "confirm": True})
    t = {x["name"]: x for x in pushes[-1][1]["tokens"]}["수요기관"]
    assert t["col"] == "수요기관명" and t["value"] == "조달청"


def test_detached_token_is_not_rebound_by_retokenize(tmp_path):
    """손으로 끊은 결속은 다음 타이핑이 도로 붙이지 않는다 — 명시 제스처의 조용한 뒤집기 금지."""
    ctrl, _ = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "사업명", "col": ""})
    snap = ctrl.dispatch("edit_source", {"text": "{{사업명}} / {{추정가격}} / {{신규}}"})
    by_name = {t["name"]: t for t in snap["tokens"]}
    assert by_name["사업명"]["col"] == "" and by_name["사업명"]["suggest"] == ""
    assert by_name["추정가격"]["col"] == "추정가격"  # 손대지 않은 자리는 그대로


def test_human_cleared_bound_value_renders_missing_not_blank(tmp_path):
    """사람이 비운 자리는 missing({{토큰}}) — blank 로 그리면 빈칸의 임자를 거짓으로 말한다."""
    ctrl, _ = _aimed(tmp_path)
    snap = ctrl.dispatch("set_token", {"name": "사업명", "text": ""})
    kinds = {s.get("name"): s["kind"] for s in snap["segments"] if s["kind"] != "literal"}
    assert kinds["사업명"] == "missing"


def test_carry_notice_wording_follows_the_gesture(tmp_path):
    """한 문장을 세 동사에 돌려쓰지 않는다 — 해제 확인이 있지도 않은 「새 데이터」를 말하면 거짓."""
    ctrl, _ = _aimed(tmp_path)
    ctrl.dispatch("set_token", {"name": "사업명", "text": "고침"})
    assert "새 데이터" in ctrl.dispatch("carry_notice", {"gesture": "swap"})["message"]
    assert "새 행" in ctrl.dispatch("carry_notice", {"gesture": "row"})["message"]
    clear = ctrl.dispatch("carry_notice", {"gesture": "clear"})["message"]
    assert "새 데이터" not in clear and "굳습니다" in clear


def test_clear_gesture_announces_ownership_transfer_of_bound_values(tmp_path):
    """해제만의 고지(#134) — 결속 값이 평문으로 굳어 소유권이 「자동」→「직접 입력」으로 넘어간다.

    값이 눈에 남으니 조용한 소실은 아니지만, 전이가 무언이면 사용자는 화면의 값이 여전히
    데이터에서 온다고 믿는다. 교체·행 이동에선 같은 자리가 조용히 재생성되므로 이 문장을
    세우지 않는다 — 제스처별 정확한 술어(over-warn 도 거짓이다).
    """
    ctrl, _ = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": "수요기관명"})
    clear = ctrl.dispatch("carry_notice", {"gesture": "clear"})
    assert clear["armed"] is False                       # 막지 않는다(고지 갈래)
    assert "수요기관" in clear["notice"] and "직접 입력" in clear["notice"]
    for gesture in ("swap", "row"):
        other = ctrl.dispatch("carry_notice", {"gesture": gesture})
        assert "굳고" not in other["notice"], (
            f"{gesture} 에서 해제 전용 문장이 섰습니다(재생성되는 자리를 소실로 말함): {other!r}"
        )


def test_manual_values_notify_without_blocking(tmp_path):
    """무결속 수기 = 유지 + **고지**(가드 아님, 결정 32) — 매 행 이동마다 모달이 서면 반복이다."""
    ctrl, _ = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": ""})
    ctrl.dispatch("set_token", {"name": "수요기관", "text": "직접 입력"})
    g = ctrl.dispatch("carry_notice", {"gesture": "row"})
    assert g["armed"] is False and "수요기관" in g["notice"]


def test_step_row_computed_server_side_and_clamped(tmp_path):
    """스테퍼는 델타를 받아 서버가 계산한다 — 양끝은 제자리(버튼이 이미 비활성인 자리)."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("step_row", {"delta": 1})
    assert pushes[-1][1]["row_idx"] == 1
    ctrl.dispatch("step_row", {"delta": 1})  # 마지막 행에서 한 칸 더
    assert pushes[-1][1]["row_idx"] == 1
    ctrl.dispatch("step_row", {"delta": -5})
    assert pushes[-1][1]["row_idx"] == 0


def test_registered_in_frontend(tmp_path, monkeypatch):
    """브리지가 빠른 기안 컨트롤러를 등록하고 initial 로 라우팅한다(등록 한 줄 결선 확인)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    assert "quickdraft" in frontend.controllers
    init = frontend.initial("quickdraft")
    assert "templates" in init and init["origin"] is None


# --------------------------------------------------- 휘발도 가드·복사·승격 표면(PR-4)

def test_session_guard_not_armed_when_empty_or_only_loaded(tmp_path):
    """빈손·미노동 세션엔 죽은 확인을 세우지 않는다(결정 32) — 템플릿만 깐 건 재선택으로 복원됨."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.dispatch("session_guard", {"gesture": "fresh"})["armed"] is False
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    assert ctrl.dispatch("session_guard", {"gesture": "fresh"})["armed"] is False


def test_session_guard_fresh_arms_and_quotes_what_is_lost(tmp_path):
    """새 기안(통째 폐기)은 저장 안 된 노동을 종류별로 인용하고 남기는 길(복사)을 일러준다."""
    ctrl, _ = _aimed(tmp_path)  # 템플릿 + 데이터 겨눔(자동 결속)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": ""})
    ctrl.dispatch("set_token", {"name": "수요기관", "text": "직접 입력"})  # 무결속 수기
    g = ctrl.dispatch("session_guard", {"gesture": "fresh"})
    assert g["armed"] is True
    assert "낙찰현황.csv" in g["message"]  # 겨눈 데이터도 사라진다(fresh = 통째)
    assert "수요기관" in g["message"] and "직접 입력" in g["message"]
    assert "복사" in g["message"]


def test_session_guard_switch_excludes_surviving_data(tmp_path):
    """전환 가드는 fresh 와 다른 술어를 쓴다 — 같은 이름·겨눈 데이터는 새 템플릿에서 이어지므로
    데이터 겨눔만으론 무장하지 않는다(지배 결함류: 확인 문안이 살아남는 것을 '사라진다'고 거짓말)."""
    ctrl, _ = _aimed(tmp_path)  # 데이터 겨눔·자동 결속만(사람 값·원문 수정 없음)
    assert ctrl.dispatch("session_guard", {"gesture": "switch"})["armed"] is False
    # 원문 수정은 전환이 실제로 버린다 → 무장. 문안은 살아남는 것도 정직하게 말한다.
    ctrl.dispatch("edit_source", {"text": "{{사업명}} 만"})
    g = ctrl.dispatch("session_guard", {"gesture": "switch"})
    assert g["armed"] is True and "이어집니다" in g["message"]


def test_paste_only_session_is_dirty_for_both_gestures(tmp_path):
    """붙여넣은 원문은 재선택 복원 경로가 없다 — 데이터·수기 없이도 새 기안·전환이 조용히
    버리면 안 된다(리뷰 F1: paste 유래 원문 자체가 노동)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("paste_template", {"text": "제목: {{공고명}}"})
    g = ctrl.dispatch("session_guard", {"gesture": "fresh"})
    assert g["armed"] is True and "붙여넣은 템플릿 원문" in g["message"]
    # 전환도 붙여넣은 원문을 교체하므로 무장 — 단 동명 자리·데이터는 이어짐을 병기한다.
    s = ctrl.dispatch("session_guard", {"gesture": "switch"})
    assert s["armed"] is True and "붙여넣은 템플릿 원문" in s["message"] and "이어집니다" in s["message"]


def test_switch_guard_states_rule_without_enumerating_values(tmp_path):
    """전환 가드는 사람 값을 '사라진다'고 이름까지 열거하지 않는다 — _retokenize 가 동명 토큰
    값을 승계하므로 열거는 거짓(리뷰 F4). 규칙만 재진술한다(집합은 대상 템플릿에 달림)."""
    ctrl, _ = _aimed(tmp_path)
    ctrl.dispatch("set_source", {"name": "수요기관", "col": ""})
    ctrl.dispatch("set_token", {"name": "수요기관", "text": "직접 입력"})  # 무결속 수기
    g = ctrl.dispatch("session_guard", {"gesture": "switch"})
    assert g["armed"] is True
    assert "수요기관" not in g["message"], "살아남을 수 있는 값을 이름까지 찍어 사라진다고 단정합니다."
    assert "이어집니다" in g["message"] and "남지 않습니다" in g["message"]


def test_empty_paste_clears_template_but_keeps_aimed_data(tmp_path):
    """빈 붙여넣기는 템플릿만 비우고 데이터 겨눔은 남긴다(리뷰 F2) — 전환 가드가 약속한
    '데이터는 이어집니다'를 지킨다. fresh 로 겨눔까지 버리면 그 약속이 거짓이 된다."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("paste_template", {"text": "   \n  "})
    snap = pushes[-1][1]
    assert snap["origin"] is None and snap["template_text"] == "" and snap["tokens"] == []
    assert snap["has_data"] is True and snap["data_source_label"] == "파일: 낙찰현황.csv"


def test_session_guard_is_query_and_does_not_push(tmp_path):
    """가드 질의는 무변이 — 확인 창을 띄우는 사이 화면이 요동치면 안 된다(carry_notice 동형)."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("set_token", {"name": "수요기관", "text": "x"})
    n = len(pushes)
    ctrl.dispatch("session_guard", {"gesture": "fresh"})
    assert len(pushes) == n


def test_fresh_empties_session(tmp_path):
    """「새 기안」 = 세션 통째 초기화(결정 32) — 빈손으로 돌아가고 재렌더를 민다."""
    ctrl, pushes = _aimed(tmp_path)
    ctrl.dispatch("fresh", {})
    snap = pushes[-1][1]
    assert snap["origin"] is None and snap["template_text"] == ""
    assert snap["tokens"] == [] and snap["has_data"] is False


def test_render_is_plain_render_record_and_can_copy_gates_on_template(tmp_path):
    """복사 계약 = 링1 render_record(평문 + 리포트). 표지는 화면 전용이라 평문엔 음영이 없다.

    미채움이 있어도 복사는 막지 않는다(완화 조항 — 사후 경보): can_copy 는 '쓸 게 아예
    없음'(빈손)만 막고, 미채움은 report 로 흘러 웹이 복사 후 시끄럽게 알린다(결정 33).
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.can_copy() is False  # 빈손 = 빈 클립보드 쓰기 차단(리뷰 F3 동형)
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    ctrl.dispatch("set_token", {"name": "사업명", "text": "행정정보시스템"})
    assert ctrl.can_copy() is True
    text, report = ctrl.render()
    assert text == "제목: 행정정보시스템 개찰 참관 보고\n금액: {{추정가격}}"
    assert report.missing_fields == ["추정가격"]  # 사후 경보 재료 — 복사를 막지 않는다


def test_copy_clipboard_bridge_writes_and_reports_unfilled(tmp_path, monkeypatch):
    """공유 copy_clipboard 브리지 관통 — 빠른 기안이 render/can_copy 로 결선돼 실제로 복사되고
    사후 경보 재료(미채움 수)를 돌려준다(txt 카드와 같은 진입점 — 손복사 없음)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    written: list = []
    monkeypatch.setattr(app_mod, "set_clipboard_text", lambda t: written.append(t))
    (tmp_path / "txt").mkdir()
    (tmp_path / "txt" / "기안.txt").write_text("{{사업명}} / {{추정가격}}", encoding="utf-8")
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    ctrl = frontend.controllers["quickdraft"]
    ctrl.dispatch("select_template", {"name": "기안"})
    ctrl.dispatch("set_token", {"name": "사업명", "text": "행정정보시스템"})
    res = frontend.copy_clipboard("quickdraft")
    assert res["copied"] is True and written == ["행정정보시스템 / {{추정가격}}"]
    assert res["missing_fields"] == ["추정가격"]  # 미채움이 리포트로 나간다(사후 경보)


def test_copy_clipboard_bridge_blocks_empty_hand(tmp_path, monkeypatch):
    """빈손(템플릿 없음)은 클립보드에 아무것도 쓰지 않는다 — 빈 쓰레기·무피드백 차단(can_copy 게이트)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    written: list = []
    monkeypatch.setattr(app_mod, "set_clipboard_text", lambda t: written.append(t))
    (tmp_path / "txt").mkdir()
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    res = frontend.copy_clipboard("quickdraft")
    assert res["copied"] is False and written == []


# ------------------- 대상 글꼴 선언·정렬 린트 합류(#134 부록 B-7 (g), 결정 17) -------------------
def test_target_font_declaration_is_read_not_copied(tmp_path, monkeypatch):
    """선언은 **전역 영속**이라 이 화면이 사본을 들지 않는다 — txt 큐에서 바꾸면 여기도 따라온다.

    사본을 들면 두 화면이 서로 다른 글꼴로 "이대로 복사됩니다"라고 말한다.
    """
    from hwpxfiller.webapp import screen_quickdraft as sq

    ctrl, _ = _controller(tmp_path)
    font = {"v": "gulimche"}
    monkeypatch.setattr(sq, "load_draft_target_font", lambda: font["v"])
    ctrl.dispatch("select_template", {"name": "개찰참관보고"})
    assert ctrl.snapshot()["target_font"] == "gulimche"
    font["v"] = "malgun"                      # 다른 화면에서 선언 변경
    assert ctrl.snapshot()["target_font"] == "malgun"


def _aligned_ctrl(tmp_path: Path, monkeypatch) -> "tuple[QuickDraftController, list]":
    """연속 공백 정렬이 있는 템플릿 + 비례폭 선언 — 린트가 발화하는 지형."""
    from hwpxfiller.webapp import screen_quickdraft as sq

    (tmp_path / "정렬.txt").write_text("수신    {{수신처}}\n제목    {{제목}}", encoding="utf-8")
    pushes: list = []
    ctrl = QuickDraftController(
        TextTemplateRegistry(tmp_path),
        lambda s, snap: pushes.append((s, snap)),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
    )
    monkeypatch.setattr(sq, "load_draft_target_font", lambda: "malgun")  # 비례폭
    ctrl.dispatch("select_template", {"name": "정렬"})
    return ctrl, pushes


def test_lint_is_declaration_conditional_and_prescribes(tmp_path, monkeypatch):
    """린트 술어는 txt 큐와 같다 — 선언-조건부 경보 + 치환 처방(표면은 판정하지 않는다)."""
    ctrl, _ = _aligned_ctrl(tmp_path, monkeypatch)
    lint = ctrl.snapshot()["lint"]
    assert lint == {"proportional": True, "space_run": True, "applied": False, "active": True}
    ctrl.dispatch("set_fullwidth", {"value": True})
    lint = ctrl.snapshot()["lint"]
    assert lint["applied"] is True and lint["active"] is True
    # 치환 후에도 space_run 이 참인 이유: 술어는 **치환 전 원문** 기준이라 "무엇을 고쳤는지"를
    # 되돌리기 상태에서도 정직하게 말한다(결정 17).
    assert lint["space_run"] is True


def test_fullwidth_applies_to_preview_and_clipboard_through_one_path(tmp_path, monkeypatch):
    """미리보기와 클립보드가 한 통로를 지난다 — 갈라지면 "보이는 것과 복사되는 것"이 어긋난다."""
    ctrl, _ = _aligned_ctrl(tmp_path, monkeypatch)
    ctrl.dispatch("set_fullwidth", {"value": True})
    text, _report = ctrl.render()
    seg_text = "".join(s["text"] for s in ctrl.snapshot()["segments"])
    assert text == seg_text
    assert "　" in text and "    " not in text      # 전각으로 치환됨
    ctrl.dispatch("set_fullwidth", {"value": False})
    assert "    " in ctrl.render()[0]                    # 되돌리면 원문 그대로


def test_fullwidth_dies_with_the_source_it_judged(tmp_path, monkeypatch):
    """치환은 그 원문에 대한 판단 — 원문이 바뀌면 함께 죽는다(txt 동형, 조용한 승계 금지)."""
    ctrl, _ = _aligned_ctrl(tmp_path, monkeypatch)
    ctrl.dispatch("set_fullwidth", {"value": True})
    ctrl.dispatch("paste_template", {"text": "새 원문 {{토큰}}"})
    assert ctrl.snapshot()["lint"]["applied"] is False
    ctrl.dispatch("set_fullwidth", {"value": True})
    ctrl.dispatch("fresh", {})
    assert ctrl.snapshot()["lint"]["applied"] is False


def test_live_source_edit_keeps_the_visible_fullwidth_decision(tmp_path, monkeypatch):
    """라이브 편집은 치환을 리셋하지 않는다(리뷰 F3 결론) — 타건마다 꺼지면 손가락 밑에서
    "적용됨"이 사라진다. 이월이 조용하지도 않다: 린트 줄이 편집 내내 「되돌리기」로 서 있고,
    미리보기와 클립보드가 한 통로라 화면이 곧 결과다.
    """
    ctrl, _ = _aligned_ctrl(tmp_path, monkeypatch)
    ctrl.dispatch("set_fullwidth", {"value": True})
    snap = ctrl.dispatch("edit_source", {"text": "수신    {{수신처}}\n참조    {{참조}}"})
    assert snap["lint"]["applied"] is True          # 이월
    assert snap["lint"]["active"] is True           # 그리고 화면에 계속 진술된다
    assert "　" in "".join(s["text"] for s in snap["segments"])
