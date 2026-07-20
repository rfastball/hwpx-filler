"""코드리뷰 3차(r3) editor 클러스터 회귀 — C1·C2·C4·C10·K2·K6·K9·K10.

에디터 컨트롤러(:mod:`hwpxfiller.webapp.screen_editor`)와 매핑 상태
(:mod:`hwpxfiller.gui.mapping_state`)의 이번 라운드 결함 봉합을 헤드리스로 고정한다.
순수 JS 지점(doSave try/catch)은 정적 계약 테스트로 커버한다.
"""
from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.mapping_state import MappingModel, profile_source_vocabulary
from hwpxfiller.webapp.screen_editor import EditorController

REPO = Path(__file__).resolve().parents[1]
TPL_COMPILED = REPO / "tests" / "corpus" / "scenario" / "templates" / "구매요청서.hwpx"
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"


def _controller(tmp_path: Path, *, pool_registry=None) -> EditorController:
    """레지스트리를 tmp 로 격리한 컨트롤러(풀은 주입 가능 — 실패/계수 더블용)."""
    return EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: None,
        pool_registry=(
            pool_registry if pool_registry is not None
            else DatasetPoolRegistry(tmp_path / "pool")
        ),
    )


def _save_named(ctrl: EditorController, name: str) -> dict:
    """스키마온리 최소 흐름으로 작업 1개 저장(저장 후 세션 리셋)."""
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": name})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})
    return ctrl.dispatch("save", {})


def _complete_with_data(ctrl: EditorController, name: str) -> None:
    """데이터(다중시트 확정) 연결 세션을 저장 직전까지 구성."""
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})   # 매핑 진입(데이터 겨눔 — 3단계 접기)
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": name})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})


# ================================================================ C1 (HIGH)
# 데이터 교체 후 매핑 자동 재확정 금지 — 값은 이월, 확정은 전원 해제.
def test_c1_data_change_never_arrives_confirmed(tmp_path):
    """키 변경 재초안에서 어떤 행도 확정 상태로 도착하지 않는다(구 불변식 복원)."""
    ctrl = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET))            # 첫 시트(공고명·추정가격)
    ctrl.dispatch("goto_step", {"step": 1})          # 매핑 진입(데이터 겨눔 — 3단계 접기)
    ctrl.dispatch("set_source", {"index": 0, "source": "추정가격"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    assert ctrl.snapshot()["is_complete"] is True

    # 같은 이름 컬럼이 의미가 다를 수 있는 새 데이터로 관문 교체 — 그 자리에서 재검토 강제.
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")   # in-place 재생성(단계 왕복 없음)
    snap = ctrl.snapshot()
    assert all(row["confirmed"] is False for row in snap["rows"])
    assert snap["is_complete"] is False              # is_complete 우회 봉쇄
    assert snap["rows"][0]["source"] == "추정가격"   # 값(제안)은 이월 — UX 유지
    assert snap["notice"] and snap["notice"]["level"] == "warn"
    assert "다시 확정" in snap["notice"]["text"]     # 재확정 필요 loud 재진술


def test_c1_apply_profile_confirm_false_carries_values_only():
    """mapping_state 계약: confirm=False 는 값만 이월하고 확정 도착 0."""
    profile = MappingProfile(mappings=[
        FieldMapping(template_field="금액", source="금액", type="amount"),
    ])
    model = MappingModel(
        rows=MappingModel.from_profile(profile).rows, source_fields=["금액"]
    )
    model.unconfirm_all()
    carried = model.apply_profile(profile, confirm=False)
    assert carried == 1                              # 이월 행 수는 보고
    assert model.confirmed_count() == 0              # 확정 도착은 없음
    assert model.rows[0].source == "금액" and model.rows[0].type == "amount"


# ================================================================ C4 (HIGH)
# 저장 후 pool 등록 실패 = 무반응 반저장 금지 — 결과 dict 로 정직 재진술.
class _FailingPool(DatasetPoolRegistry):
    def save(self, item, *, allow_overwrite: bool = False) -> None:  # noqa: ARG002
        raise OSError("디스크 쓰기 실패(시뮬레이션)")


def test_c4_pool_register_failure_is_restated_not_swallowed(tmp_path):
    ctrl = _controller(tmp_path, pool_registry=_FailingPool(tmp_path / "pool"))
    _complete_with_data(ctrl, "반저장작업")
    res = ctrl.dispatch("save", {})                  # 예외가 dispatch 밖으로 새지 않는다
    assert res["ok"] is True                         # 작업 저장 자체는 성공
    assert res["saved_name"] == "반저장작업"
    assert res["dataset_registered"] == ""           # 등록은 실패 — 성공으로 뭉개지 않음
    assert "등록에 실패" in res["dataset_register_error"]
    assert "multi_sheet" in res["dataset_register_error"]
    assert JobRegistry(tmp_path / "jobs").exists("반저장작업")  # 반저장 상태의 정직 재진술


def test_c4_editor_js_dosave_guards_and_surfaces_half_save():
    """정적 계약: doSave 는 try/catch 로 감싸고 dataset_register_error 를 표면화한다."""
    src = (REPO / "web" / "js" / "screens" / "editor.js").read_text(encoding="utf-8")
    start = src.index("async function doSave")
    body = src[start:start + 2000]
    assert "try {" in body and "catch" in body       # 브리지 예외 무반응 금지
    assert "dataset_register_error" in body          # 반저장 경고 표면화


def test_editor_js_gateway_guards_confirmed_mapping_reset():
    """PR#105 F1 정적 계약 — 관문 데이터 교체/비우기(pick-data·skip-data)는 사람 소유 매핑이
    있으면 파괴 전 확인한다(confirmMappingResetIfConfirmed — 수치는 Python stakes 질의).
    편집 복원 확정이 매핑 표 바로 위 관문의 1클릭으로 조용히 미확정 재초안되던 것을 막는다."""
    from test_r3_pool import _segment
    src = (REPO / "web" / "js" / "screens" / "editor.js").read_text(encoding="utf-8")
    assert "async function confirmMappingResetIfConfirmed" in src, "확정 보호 가드 헬퍼 부재(F1)."
    assert "mapping_reset_stakes" in src, "가드 수치의 Python 즉시 질의 배선 부재(리뷰 F7)."
    body = _segment(src, "async function onClick", "function onChange")
    # pick-data·skip-data 두 파괴 경로 모두 가드를 통과한다(둘 다 _ensure_model 재초안 유발).
    assert body.count("confirmMappingResetIfConfirmed(") >= 2, (
        "관문 파괴 경로(pick-data·skip-data)에 확정 보호 가드가 둘 다 걸리지 않았습니다(F1)."
    )


def test_editor_js_click_dispatch_guards_bridge_rejection():
    """정적 계약(#45): onClick 디스패처가 try/catch + alert 로 브리지 rejection 을 가드한다.

    개별 핸들러만 감싸는 처치는 다음 핸들러를 또 빠뜨린다(실제로 profile_* 봉합 라운드에서
    confirmAll 이 무방비로 남아 있었다) — pool.js onListClick 미러로 가드를 디스패처에 두고,
    awaited 핸들러 전부가 상속하게 고정한다. 절단은 test_r3_pool._segment 공유(단일 슬라이서).
    """
    import re

    from test_r3_pool import _segment
    src = (REPO / "web" / "js" / "screens" / "editor.js").read_text(encoding="utf-8")
    body = _segment(src, "async function onClick", "function onChange")
    assert "try {" in body and "catch" in body and "window.alert" in body, (
        "onClick 디스패처가 브리지 rejection 을 가드하지 않습니다 — 무반응 버튼(#45)."
    )
    # awaited 여야 rejection 이 디스패처 가드로 올라온다 — fire-and-forget 강등 금지.
    # 개별 이름 나열이 아니라 onClick 안의 **모든** Bridge.* 호출을 검사한다(PR #46 P2 —
    # ack_gate·step_preview 등 직접 호출이 무대기라 가드 밖으로 새던 잔여 봉합).
    unawaited = re.findall(r"(?<!await )Bridge\.\w+\(", body)
    assert not unawaited, (
        f"onClick 안에 await 없는 Bridge 호출이 있습니다 — rejection 이 가드 밖으로 샙니다(#45): "
        f"{unawaited}"
    )
    for frag in ("await confirmAll()", "await doSave({})"):
        assert frag in body, f"onClick 이 '{frag}' 로 대기하지 않습니다 — 가드 상속 단절(#45)."
    # confirmAll 내부 2차 호출(confirm_blanks)도 fire-and-forget 이면 가드 밖으로 샌다.
    confirm_body = _segment(src, "async function confirmAll", "async function doSave")
    assert 'await Bridge.call(SCREEN, "confirm_blanks"' in confirm_body, (
        "confirmAll 의 confirm_blanks 호출이 awaited 가 아닙니다 — rejection 이 삼켜집니다(#45)."
    )


# ================================================================ C10 (MED)
# 자기-갱신 저장이라도 편집 중 외부 변경은 무확인으로 덮지 않는다.
def test_c10_self_update_confirms_when_disk_changed_externally(tmp_path):
    ctrl = _controller(tmp_path)
    assert _save_named(ctrl, "외부변경작업")["ok"] is True
    ctrl.load_job("외부변경작업")
    # 편집 세션이 열린 사이 외부에서 같은 이름 작업의 내용을 교체.
    reg = JobRegistry(tmp_path / "jobs")
    job = reg.load("외부변경작업")
    job.filename_pattern = "외부-{{ID}}"
    reg.save(job, allow_overwrite=True)

    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert "외부" in res["overwrite_text"]           # '편집 중 외부 변경' 문구
    # 재진술 확인 후에만 덮어쓴다.
    assert ctrl.dispatch("save", {"confirm_overwrite": True})["ok"] is True


def test_c10_unchanged_self_update_saves_without_confirm(tmp_path):
    """무변경(및 태그·마지막 실행만 변경) 자기-갱신은 종전대로 무확인 저장."""
    ctrl = _controller(tmp_path)
    _save_named(ctrl, "무변경작업")
    ctrl.load_job("무변경작업")
    # 태그·마지막 실행은 지문에서 제외 — 홈 태그 편집과의 공존(저장이 디스크 값 보존).
    reg = JobRegistry(tmp_path / "jobs")
    job = reg.load("무변경작업")
    job.tags = {"물품": "의약품"}
    job.last_run_at = "2026-07-15T10:00:00"
    reg.save(job, allow_overwrite=True)
    res = ctrl.dispatch("save", {})
    assert res["ok"] is True                         # 확인 왕복 없음
    saved = reg.load("무변경작업")
    assert saved.tags == {"물품": "의약품"}          # 보존 경로도 그대로


def test_c10_self_update_confirms_when_origin_corrupted(tmp_path):
    """원점 파일이 손상돼 내용 불명이면 조용히 덮지 않고 확인을 승격한다."""
    ctrl = _controller(tmp_path)
    _save_named(ctrl, "손상작업")
    ctrl.load_job("손상작업")
    reg = JobRegistry(tmp_path / "jobs")
    reg.path_for("손상작업").write_text("{손상", encoding="utf-8")
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert "손상" in res["overwrite_text"]
    assert ctrl.dispatch("save", {"confirm_overwrite": True})["ok"] is True


def test_c10_self_update_after_external_delete_recreates_without_confirm(tmp_path):
    """원점이 삭제됐으면 덮을 기존 내용이 없다 — 확인 없이 재생성."""
    ctrl = _controller(tmp_path)
    _save_named(ctrl, "삭제작업")
    ctrl.load_job("삭제작업")
    reg = JobRegistry(tmp_path / "jobs")
    reg.delete("삭제작업")
    assert ctrl.dispatch("save", {})["ok"] is True
    assert reg.exists("삭제작업")


# ================================================================ K9
# 저장 1회 = 같은 .dataset.json 로드 1회(게이트 stash 재사용, 판정 표류 제거).
class _CountingPool(DatasetPoolRegistry):
    def __init__(self, directory):
        super().__init__(directory)
        self.load_calls = 0

    def load(self, name: str) -> DatasetPoolItem:
        self.load_calls += 1
        return super().load(name)


def test_k9_save_loads_existing_dataset_once_and_preserves_lifecycle(tmp_path):
    pool = _CountingPool(tmp_path / "pool")
    prior = DatasetPoolItem(
        name="multi_sheet", kind="excel", opts={"path": "old.xlsx"}, note="보존메모")
    prior.archive()
    pool.save(prior)

    ctrl = _controller(tmp_path, pool_registry=pool)
    _complete_with_data(ctrl, "계수작업")
    pool.load_calls = 0
    res = ctrl.dispatch("save", {"confirm_dataset": True})
    assert res["ok"] is True and res["dataset_registered"] == "multi_sheet"
    assert pool.load_calls == 1                      # 게이트 1회 로드 → 등록은 stash 재사용
    item = pool.load("multi_sheet")
    assert item.status == "archived" and item.note == "보존메모"  # 수명·메모 보존 유지
    assert item.opts["path"] == str(MULTI_SHEET) and item.opts["sheet"] == "낙찰현황"


# ================================================================ r4 (cross-kind)
def test_r4_cross_kind_dataset_confirm_restates_and_normalizes_kind(tmp_path):
    """동명 비-excel 항목 자동등록 확정 = 확인 문구에 종류 전이 재진술 + kind 정규화.

    _do_save 의 보존 갱신(stash 재사용)이 opts 만 갈아끼우면 kind=nara + opts={path}
    하이브리드 손상 항목이 생긴다 — 풀 피커 겨눔 시 나라 동결 문구로 거절되고 요약이
    "기간 ?~?" 가 된다(pool 화면 update_excel_reference 미러, confirm-or-alarm).
    """
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(
        name="multi_sheet", kind="nara",
        opts={"bgn_dt": "202601010000", "end_dt": "202601310000"}))
    ctrl = _controller(tmp_path, pool_registry=pool)
    _complete_with_data(ctrl, "전이작업")  # 데이터=multi_sheet.xlsx → 데이터셋명 동명 충돌

    # 1차: 게이트 확인 문구가 종류 전이(나라장터→엑셀/CSV)를 재진술한다.
    res1 = ctrl.dispatch("save", {})
    assert res1.get("needs_dataset_confirm") is True
    assert "나라장터 → 엑셀/CSV" in res1["dataset_text"]

    # 2차(confirm): kind/opts 정합 착지 — 수명 보존 갱신이어도 하이브리드 손상 금지.
    res2 = ctrl.dispatch("save", {"confirm_dataset": True})
    assert res2["ok"] is True and res2["dataset_registered"] == "multi_sheet"
    item = pool.load("multi_sheet")
    assert item.kind == "excel"
    assert item.opts == {"path": str(MULTI_SHEET), "sheet": "낙찰현황"}


# ================================================================ K10
def test_k10_profile_source_vocabulary_is_shared_single_source(tmp_path):
    """어휘 합집합 단일 출처 — 중복 제거·선언순, malformed blank+source 유령 키 배제."""
    profile = MappingProfile(mappings=[
        FieldMapping(template_field="a", source="갑", type="text"),
        FieldMapping(template_field="b", source="유령", type="blank"),  # malformed
        FieldMapping(template_field="c", source="갑", type="text"),     # 중복
        FieldMapping(template_field="d", source="을", type="text"),
    ])
    assert profile_source_vocabulary(profile) == ["갑", "을"]
    # from_profile 과 동일 합집합(공유 확인).
    assert MappingModel.from_profile(profile).source_fields == ["갑", "을"]

    # load_job(에디터 복원)도 같은 합집합을 쓴다.
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="어휘작업", template_path=str(TPL_COMPILED), mapping=profile))
    ctrl = _controller(tmp_path)
    ctrl.load_job("어휘작업")
    assert ctrl.source_fields == ["갑", "을"]


def test_editor_js_template_stage_is_library_first():
    """정적 계약(R-info 2부) — 신규 1단계는 라이브러리 피커가 정본: 생 파일 직접 로드
    (pick-template)는 소멸하고, 라이브러리 선택(use-library)과 가져오기=복사
    (import-template)만 남는다. 토큰 참조는 접힘(F27)."""
    src = (REPO / "web" / "js" / "screens" / "editor.js").read_text(encoding="utf-8")
    assert 'data-act="pick-template"' not in src, "생 파일 직접 로드 버튼이 부활했습니다(2부 위반)."
    assert 'data-act="use-library"' in src, "라이브러리 선택 배선이 없습니다."
    assert 'data-act="import-template"' in src, "가져오기=복사 배선이 없습니다."
    assert "pattern_preview" in src, "파일명 라이브 예시(F26) 소비가 없습니다."
