"""코드리뷰 3차(r3) editor 클러스터 회귀 — C1·C2·C4·C10·K2·K6·K9·K10.

에디터 컨트롤러(:mod:`hwpxfiller.webapp.screen_editor`)와 매핑 상태
(:mod:`hwpxfiller.gui.mapping_state`)의 이번 라운드 결함 봉합을 헤드리스로 고정한다.
순수 JS 지점(doSave try/catch)은 정적 계약 테스트로 커버한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from _web_source import REPO_ROOT, SOURCE_JS_DIR
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.mapping_state import MappingModel, profile_source_vocabulary
from hwpxfiller.webapp.screen_editor import EditorController

REPO = REPO_ROOT
#: R4-02 — 편집기 표면이 `frontend/js/screens/editor.js` 에서 React 로 옮겼다. 정적 계약이
#: 겨누는 것은 파일이 아니라 **거처**라, 경로만 후계로 바꾸고 물음은 그대로 둔다.
EDITOR_TS = (SOURCE_JS_DIR.parent / "src" / "screens" / "editor.ts").read_text(encoding="utf-8")
ENTRY_TS = (SOURCE_JS_DIR.parent / "src" / "screens" / "editor_entry.ts").read_text(
    encoding="utf-8")
TPL_COMPILED = REPO / "tests" / "corpus" / "scenario" / "templates" / "구매요청서.hwpx"
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"


def _controller(tmp_path: Path) -> EditorController:
    """레지스트리를 tmp 로 격리한 컨트롤러(#347: 풀 주입은 자동등록과 함께 사망)."""
    from hwpxfiller.core.text_registry import TextTemplateRegistry

    return EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: None,
        text_registry=TextTemplateRegistry(tmp_path / "text_templates"),
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
    ctrl.dispatch("goto_section", {"section": "binding"})   # 매핑 진입(데이터 겨눔 — 3단계 접기)
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
    ctrl.dispatch("goto_section", {"section": "binding"})          # 매핑 진입(데이터 겨눔 — 3단계 접기)
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
# (구 C4 반저장(작업 저장 성공+풀 등록 실패) 재진술 계약은 #347 에서 자동등록과 함께
#  소멸 — 저장이 풀에 쓰지 않으므로 반저장 상태 자체가 없다. 브리지 예외 무반응 금지
#  계약(doSave try/catch)은 아래 정적 가드가 계속 진다.)
def test_c4_editor_js_dosave_guards_bridge_exception(tmp_path):
    """정적 계약: doSave 는 try/catch 로 감싸 브리지 예외 무반응을 막는다."""
    src = EDITOR_TS
    start = src.index("async function doSave")
    body = src[start:start + 2000]
    assert "try {" in body and "catch" in body       # 브리지 예외 무반응 금지
    # 자동등록 반저장 표면(dataset_register_error)은 게이트째 사망(#347) — 부활 금지.
    assert "dataset_register_error" not in src
    assert "needs_dataset_confirm" not in src
    ctrl = _controller(tmp_path)
    _complete_with_data(ctrl, "무풀저장작업")
    res = ctrl.dispatch("save", {})
    assert res == {"ok": True, "saved_name": "무풀저장작업"}  # 등록 관련 키 없음
    assert DatasetPoolRegistry(tmp_path / "pool").list_items() == []


def test_editor_js_gateway_guards_confirmed_mapping_reset():
    """PR#105 F1 정적 계약 — 관문 데이터 교체/비우기(pick-data·skip-data)는 사람 소유 매핑이
    있으면 파괴 전 확인한다(confirmMappingResetIfConfirmed — 수치는 Python stakes 질의).
    편집 복원 확정이 매핑 표 바로 위 관문의 1클릭으로 조용히 미확정 재초안되던 것을 막는다."""
    src = EDITOR_TS
    assert "async function confirmMappingResetIfConfirmed" in src, "확정 보호 가드 헬퍼 부재(F1)."
    assert "mapping_reset_stakes" in src, "가드 수치의 Python 즉시 질의 배선 부재(리뷰 F7)."
    # R4-02 — 절단이 「onClick 디스패처 본문」에서 **두 행동 함수**로 바뀌었다. 물음은 그대로:
    # pick-data·skip-data 두 파괴 경로가 **둘 다** 가드를 통과하는가(둘 다 재초안을 유발한다).
    for fn in ("async function pickData", "async function skipData"):
        body = src[src.index(fn):]
        body = body[:body.index(chr(10) + "  }") + 4]
        assert "confirmMappingResetIfConfirmed(" in body, (
            f"{fn} 에 확정 보호 가드가 걸리지 않았습니다(F1)."
        )
    assert src.count("await confirmMappingResetIfConfirmed(") == 2


def test_editor_js_click_dispatch_guards_bridge_rejection():
    """정적 계약(#45): onClick 디스패처가 try/catch + alert 로 브리지 rejection 을 가드한다.

    개별 핸들러만 감싸는 처치는 다음 핸들러를 또 빠뜨린다(실제로 profile_* 봉합 라운드에서
    confirmAll 이 무방비로 남아 있었다) — pool.js onListClick 미러로 가드를 디스패처에 두고,
    awaited 핸들러 전부가 상속하게 고정한다. 절단은 test_r3_pool._segment 공유(단일 슬라이서).
    """
    import re

    src = EDITOR_TS
    # R4-02 — 「하나의 자리」가 onClick 디스패처에서 `guarded` 로 옮겼다. 개별 핸들러를
    # 각자 감싸는 처치는 다음 핸들러를 또 빠뜨린다는 것이 이 계약의 이유이고, 그 이유는
    # 안 바뀐다: 재진술의 거처는 **하나**다.
    body = src[src.index("function guarded("):]
    body = body[:body.index(chr(10) + "  }") + 4]
    assert "try {" in body and "catch" in body and "deps.notify(" in body, (
        "guarded 가 rejection 을 재진술하지 않습니다 — 무반응 버튼(#45)."
    )
    assert "result.catch(" in body, (
        "동기 throw 만 잡고 비동기 rejection 을 안 잡습니다 — 대부분의 행동이 async 입니다."
    )
    # 왕복하는 행동을 부르는 자리는 **전부** 그 하나를 지난다. 열거 대신 controller 의
    # **async 표면**을 원천에서 읽어 대조한다 — 새 async 행동을 더하면서 핸들러를 맨손으로
    # 달면 여기서 시끄럽다(fire-and-forget 강등 금지의 후계).
    async_surface = set(re.findall(r"^  async function (\w+)\(", src, re.M))
    async_surface |= {"sendEdit", "refreshLibrary"}   # 체인·채널 직행도 promise 다
    assert {"leaveTo", "doSave", "confirmAll", "pickData"} <= async_surface, (
        f"async 표면을 못 읽었습니다(계측 실패): {sorted(async_surface)}"
    )
    handlers = re.findall(r"on(?:Click|Change|Blur|Focus|Input|KeyDown): .*", src)
    bare = [
        line for line in handlers
        if any(f"controller.{name}(" in line for name in async_surface)
        and "controller.guarded(" not in line
    ]
    assert not bare, (
        "가드를 안 지나는 행동 핸들러가 있습니다 — rejection 이 재진술 밖으로 샙니다(#45): "
        f"{bare}"
    )
    # 양성 대조 — 위 술어가 실제로 무언가를 보고 있다(전부 통과가 「핸들러 0」이 아니다).
    assert sum("controller.guarded(" in line for line in handlers) >= 20
    # confirmAll 내부 2차 호출(confirm_blanks)도 fire-and-forget 이면 가드 밖으로 샌다.
    confirm_body = src[src.index("async function confirmAll"):]
    confirm_body = confirm_body[:confirm_body.index(chr(10) + "  }") + 4]
    assert 'await sendEdit("confirm_blanks"' in confirm_body, (
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
    assert ctrl.dispatch(
        "save", {"confirm_overwrite": True, "confirmed_overwrite_text": res["overwrite_text"]}
    )["ok"] is True


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
    assert ctrl.dispatch(
        "save", {"confirm_overwrite": True, "confirmed_overwrite_text": res["overwrite_text"]}
    )["ok"] is True


def test_c10_self_update_after_external_delete_recreates_without_confirm(tmp_path):
    """원점이 삭제됐으면 덮을 기존 내용이 없다 — 확인 없이 재생성."""
    ctrl = _controller(tmp_path)
    _save_named(ctrl, "삭제작업")
    ctrl.load_job("삭제작업")
    reg = JobRegistry(tmp_path / "jobs")
    reg.delete("삭제작업")
    assert ctrl.dispatch("save", {})["ok"] is True
    assert reg.exists("삭제작업")


# ================================================================ K9·r4 (역사)
# (K9 — 자동등록의 mutate 잠금 재읽기(#182)·r4 — cross-kind 자동등록 정규화는 #347 에서
#  자동등록째 사망. 같은 내구성·정규화 계약은 pool `relink`/`register_excel` 경로가 지고
#  test_webapp_pool·test_dataset_pool_state 가 가드한다.)


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
    src = EDITOR_TS
    assert '"pick-template"' not in src, "생 파일 직접 로드 버튼이 부활했습니다(2부 위반)."
    assert '"data-act": "use-library"' in src, "라이브러리 선택 배선이 없습니다."
    assert '"data-act": "import-template"' in src, "가져오기=복사 배선이 없습니다."
    assert "pattern_preview" in src, "파일명 라이브 예시(F26) 소비가 없습니다."


def test_editor_shares_tpl_library_vm_wiring():
    """조립 계약(PR-4 리뷰 F2) — 에디터의 템플릿 라이브러리는 tpl 화면 VM 과 같은 인스턴스
    (라이브러리=단일 실체: 폴더 재지정이 두 표면에 함께 반영). 배선이 떨어지면 신규 1단계
    피커·가져오기가 관리 화면이 안 보여주는 폴더로 조용히 발산한다."""
    src = (REPO / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    assert "template_library=tpl_ctrl.vm" in src, "에디터-tpl 라이브러리 VM 공유 배선 소실."


def test_discard_confirm_has_single_source():
    """정적 계약(PR-4 리뷰 F9) — 미저장 정의 폐기 확인은 EditorEntry.confirmDiscard 단일
    출처(3중 복붙은 문구·판정 드리프트 표면). 소비처 셋 전부가 그 헬퍼를 부른다."""
    entry = ENTRY_TS
    assert "async function confirmDiscard" in entry, "confirmDiscard 단일 정의 소실."
    # 홈 ＋ 는 newDraft(내부가 confirmDiscard)로 한 층 더 수렴했다(PR-5 리뷰 F2).
    for path, rel, needle in (
        (SOURCE_JS_DIR.parent / "src" / "screens" / "library.ts",
         "src/screens/library.ts", "deps.ports.editorEntry.current().newDraft"),
        # (template.js 는 화면과 함께 사망(F8) — 그 소비처였던 「이 서식으로 새 작업」의
        #  폐기 확인은 편집기 안 use-library 의 confirmNewSessionIfUnsaved 가 잇는다.)
        (SOURCE_JS_DIR.parent / "src" / "screens" / "editor.ts",
         "src/screens/editor.ts", "deps.ports.editorEntry.current().confirmDiscard"),
    ):
        src = path.read_text(encoding="utf-8")
        assert needle in src, f"{rel} 가 폐기 확인 단일 출처({needle})를 쓰지 않습니다."
    # 편집(탭) 맥락 전환 확인(리뷰 F1) — 클린 복원이어도 맥락 닫힘은 의식적이어야 한다.
    assert "편집을 닫고 새 작업 초안" in EDITOR_TS, "편집 맥락 전환 확인 문구가 사라졌습니다(F1)."


def test_editor_library_management_wiring_is_static():
    """정적 계약(F8 — §10.17.2 판정 B·D): tpl 화면 사망의 승계 배선.

    ①편집기가 tpl 채널 push 를 구독해 관리 동사의 결과를 재당김으로 되그린다(구독이 없으면
    가져오기·삭제·그룹 변경이 다음 진입까지 비가시) ②관리 동사는 tpl 채널을 **리터럴**로
    부른다(잠금·경로 검증·휴지통 규율이 사는 채널 — 편집기 채널 재구현 금지) ③기제는 공용
    팩토리·기존 DOM 재사용(F2 교훈 ④ — 옮기지 말고 공유).
    """
    src = EDITOR_TS
    # R4-02 — tpl 채널 구독은 `Bridge.onPush` 에서 store 채널 model 구독이 됐고, 그 push 는
    # editor 스냅샷 **재당김**을 태운다(성형의 정본은 editor 스냅샷 하나).
    assert "tplModel.subscribe(" in src, "tpl push 구독 소실 — 관리 결과가 편집기에 비가시."
    assert "deps.runtime.refresh(SCREEN)" in src, "tpl push 뒤 재당김이 없습니다."
    for action in ("set_group", "rename_group", "disband_group", "delete", "undo_delete"):
        assert f'dispatch("tpl", "{action}"' in src, (
            f"관리 동사 {action} 이 tpl 채널을 부르지 않습니다 — 채널 재구현 금지."
        )
    # 기제 공유: 메뉴 팩토리와 그룹 이동 다이얼로그는 **주입**으로 받는다(재구현 금지).
    bootstrap = (SOURCE_JS_DIR.parent / "src" / "bootstrap.js").read_text(encoding="utf-8")
    assert 'rowMenu: GroupList.createMenu({ menuId: "tplRowMenu" }),' in bootstrap
    assert "groupMove: GroupMove," in bootstrap
    for shared in ("deps.rowMenu.show(", "deps.groupMove.open(",
                   '"lib-assign"', '"lib-more"', '"lib-grp-more"'):
        assert shared in src, f"관리 기제 공유 배선 소실: {shared}"


def test_bridge_push_supports_multiple_subscribers_per_screen():
    """정적 계약(F8) — 한 채널 복수 구독: 병존 기간 editor 가 tpl push 를 함께 듣는다.
    단일 슬롯(덮어쓰기)으로 되돌리면 나중 등록이 먼저 등록을 조용히 밀어내 화면 하나가
    렌더를 잃는다(template.js ↔ editor.js 어느 쪽이든 init 순서 복권)."""
    bridge = (SOURCE_JS_DIR / "bridge.js").read_text(encoding="utf-8")
    assert "renderers[screen] = renderers[screen] || []" in bridge, (
        "onPush 가 복수 구독을 지원하지 않습니다 — 덮어쓰기 단일 슬롯은 조용한 렌더 소실."
    )
    assert "for (const fn of renderers[screen] || [])" in bridge, (
        "__push 가 구독자 전부를 부르지 않습니다."
    )


def test_every_editing_control_counts_toward_the_save_gate():
    """편집 컨트롤은 **전부** 저장 게이트의 대기 판정에 든다(U2 §2.4 R3).

    「변경 저장」은 `s.dirty || <아직 안 보낸 편집이 있는가>` 로 열린다. 앞엣것은 Python 이
    blur 뒤에야 아는 사실이고, 뒤엣것은 그 사이를 메우는 웹의 사실이다. 대상 목록이 발신
    목록보다 좁으면 **빠진 컨트롤에서만** 첫 클릭이 삼켜진다 — 실제로 첫 판은 머리·꼬리
    3입력만 세어 매핑 행의 상수 입력(`row-const`)이 그 상태였다(리뷰 R3).

    R4-02 가 그 두 목록을 **하나**로 만들었다. 「아직 안 보낸 편집」의 소유자가 draft
    reducer 하나이고(`hasPendingEdits`), 그 정의역은 `editorServerValues` 가 낸 키 전수다.
    그래서 물음이 「두 목록이 같은가」에서 「모든 컨트롤이 그 하나를 지나는가」로 좁아진다 —
    reducer 를 우회해 값을 들고 있는 컨트롤이 생기면 그 값은 게이트에 안 든다.
    """
    src = EDITOR_TS
    gate = re.search(r"const armed = ([^;]+);", src)
    assert gate, "저장 게이트 판정을 찾지 못했습니다 — 계약이 겨눌 자리가 사라졌습니다."
    assert "hasPendingEdits(draft)" in gate.group(1), (
        "게이트가 draft 의 대기 편집을 세지 않습니다 — blur 전 첫 클릭이 삼켜집니다."
    )
    assert "snapshot.dirty" in gate.group(1), "게이트가 Python 의 dirty 를 안 봅니다."

    # 값을 들고 있는 컨트롤 전수 = reducer 표시값(`valueOf`)을 읽는 자리. 그 각각은 변경을
    # reducer 로 돌려줘야(`type`/`commitRow`) 대기가 세어진다 — 한쪽만 있으면 우회다.
    controls = re.findall(r"valueOf\(draft, ([\w.]+(?:\(index, \"\w+\")?)", src)
    assert len(controls) >= 6, f"reducer 표시값을 읽는 컨트롤이 너무 적습니다(계측 실패): {controls}"
    # 이름·규칙 두 머리 입력과 행 축 넷 전부가 그 하나를 지난다.
    axes = {axis for entry in controls for axis in re.findall(r'"(\w+)"', entry)}
    assert axes == {"source", "type", "fmt", "const"}, axes
    for handler in ("controller.type(", "controller.commitRow(", "controller.commitField(",
                    "controller.commitRowOnBlur("):
        assert handler in src, f"편집 반영 경로 {handler} 가 사라졌습니다."
    # 우회 금지 — 컨트롤이 스냅샷 값을 직접 그리면 draft 가 그 칸의 주인이 아니게 된다.
    stray = re.findall(r"value: snapshot\.\w+", src)
    assert not stray, f"reducer 를 우회해 스냅샷 값을 직접 든 컨트롤: {stray}"
