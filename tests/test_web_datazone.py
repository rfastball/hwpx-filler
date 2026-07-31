"""데이터 존 공용 팩토리(슬라이스 6 PR-2a) 정적 가드 — job.js 추출의 단일 출처·분리 계약.

「작업」 화면의 데이터 존 ~450줄(열 필터 패널·필터 테이블/Shift 선택·칩 줄·필터 밖 선택
스트립·자모 하이라이트 세그먼트)을 ``frontend/js/datazone.js`` 의 ``DataZone.create(config)``
팩토리로 추출했다(#90 착지 6). 둘째 소비자였던 「기안」 큐는 화면과 함께 사망(F6 PR-B) —
현재 소비자는 job 하나지만 팩토리·화면 불가지 계약은 다음 소비자를 위해 그대로 산다.
이 모듈은 추출이 조용히 되감기는 회귀를 정적으로 차단한다:

1. 팩토리 존재·로드 순서(esc.js < datazone.js < screens/job.js).
2. job.js 가 실제로 소비(DataZone.create) — 정의 삭제만 하고 미배선 방지.
3. 데이터 존 디스패치 리터럴의 단일 출처 — job.js 재중복은 #94(링2 400줄 중복)와 동형의
   결함 클래스라 팩토리에만 있어야 한다.
4. 화면 불가지 — 팩토리에 job 고유 id(``jobXxx``)·화면 루트가 하드코딩되면 다음 소비
   인스턴스가 조용히 첫 화면 DOM 을 만진다(getElementById 는 숨은 화면으로도 해소된다).
5. 팝오버 바깥-닫기 = popover.js 단일 출처(PR 리뷰) — 기제(suppress 플래그·캡처 소비·
   pointerdown·Escape)는 Popover.wireDismiss 만 소유하고, 메뉴(job.js)·열 패널(팩토리)은
   각자 술어(isOpen·contains·close)만 주입한다. 손수 판 사본이 되살아나면 드리프트 재개.
6. 팩토리 LAST 관측 계약(PR 리뷰) — 화면이 존 렌더를 hasJob 로 게이트해도 스냅샷 관측
   (dz.sync)은 무조건이어야 한다. 빠지면 flushPendingSearch 가 직전 세션의 stale 스냅샷으로
   죽은 세션에 filter_search 를 오발한다(master 의 "무조건 LAST = s" 계약).

실 거동 패리티(가시 행·하이라이트·칩·스트립·패널 기본 닫힘·메뉴 개폐)는 실앱 WebView2
게이트(test_web_selftest_gate)가 같은 id 로 되읽어 담보한다 — 여기는 구조만.
"""
from __future__ import annotations

import re

from _web_source import (
    SOURCE_ENTRY,
    SOURCE_JS_DIR,
    app_css,
    evaluated_modules,
    evaluation_site,
)

DZ_JS = SOURCE_JS_DIR / "datazone.js"
POPOVER_JS = SOURCE_JS_DIR / "popover.js"
JOB_JS = SOURCE_JS_DIR / "screens" / "job.js"
LIB_JS = SOURCE_JS_DIR / "screens" / "library.js"
# (draftsession.js·screens/draft.js 상수 삭제 — 「기안」 화면 사망, F6 PR-B.)

# 데이터 존이 소유하는 디스패치 액션 — 전부 팩토리 단일 출처여야 한다(가드 3).
ZONE_ACTIONS = (
    "filter_panel", "filter_col_text", "filter_col_values", "filter_clear_col",
    "filter_col_range", "filter_search", "filter_reapply", "filter_prune",
    "filter_clear", "toggle_record", "select_range", "set_all", "set_none",
)


def _strip_js_comments(text: str) -> str:
    """블록 주석 + 공백 선행 줄끝 // 주석 제거 — 남는 본문은 코드·문자열.

    ``test_ux_copy_round._strip_js_comments`` 와 동일 규약. 주석은 계약 설명("jobRow-" 예시
    등)을 담을 수 있어 스캔 대상이 아니다 — 가드는 코드 하드코딩만 본다.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", text)


def test_factory_exists_and_exposes_create():
    """datazone.js 가 window.DataZone.create 팩토리를 노출한다(가드 1)."""
    src = DZ_JS.read_text(encoding="utf-8")
    assert "export function createDataZone" in src, (
        "datazone.js 가 createDataZone 팩토리를 내보내지 않습니다."
    )
    assert "function create(cfg)" in src, "DataZone 팩토리(create)가 없습니다."


def test_load_order_esc_then_shared_then_screens():
    """공급이 소비 화면(job)보다 먼저 서는가 — N-06 후계.

    (「기안」 소비자는 화면과 함께 사망 — F6 PR-B. 남은 소비 화면은 job 하나다.)

    소비 화면이 ESM factory 가 되면서(N-06) 이 순서 질문은 전부 **언어 규칙**으로 넘어갔다:
    esc·popover 는 job.js 자신의 static import 간선이라 평가가 항상 먼저고(간선 전수는
    ``test_frontend_build_graph`` 의 대조가 단언), datazone 은 compat 이 구성한 산물을 factory
    인자로 주입하므로 미구성 값은 조용한 undefined 가 아니라 구성 시점의 ReferenceError 로
    시끄럽게 죽는다. 여기 남는 질문은 원래의 결함을 막던 배선 자체다 — ①세 공급자가 여전히
    제품 그래프(compat)에 닿고 ②job 이 그 공급을 같은 이름으로 실제 소비하는가.
    """
    modules = evaluated_modules(SOURCE_ENTRY.read_text(encoding="utf-8"))
    providers = {name: evaluation_site(name)
                 for name in ("esc.js", "popover.js", "datazone.js")}

    for name, site in providers.items():
        assert site in modules, f"{name} 의 공급 지점({site})이 제품 entry 에 없습니다."
        assert name not in modules, (
            f"{name} 이 entry 에 직접 남아 있습니다 — 두 경로로 들어오면 순서 추론이 무의미해집니다."
        )
    job_src = JOB_JS.read_text(encoding="utf-8")
    assert re.search(r'(?m)^import \{ escHtml \} from "\.\./esc\.js";', job_src), (
        "job.js 가 escHtml 을 ESM import 하지 않습니다 — 공급 배선이 끊겼습니다."
    )
    assert re.search(r'(?m)^import \{ Popover \} from "\.\./popover\.js";', job_src), (
        "job.js 가 Popover 를 ESM import 하지 않습니다 — 공급 배선이 끊겼습니다."
    )
    assert re.search(
        r"export function createJobScreen\(\{[^}]*\bDataZone\b", job_src
    ), "job.js factory 가 DataZone 을 주입받지 않습니다 — 공급 배선이 끊겼습니다."


def test_job_consumes_factory_with_job_identity():
    """job.js 가 팩토리를 소비하고 화면 고유값(행 id 접두·선두 「문서」 열)을 주입한다(가드 2).

    rowIdPrefix 는 preserve.js 의 id 기반 포커스 복원 계약 — 접두가 바뀌면 재렌더 시
    포커스 복원이 조용히 깨진다. 선두 열 머리 「문서」는 F33 승계 표면.
    """
    src = JOB_JS.read_text(encoding="utf-8")
    assert "DataZone.create({" in src, "job.js 가 DataZone.create 를 소비하지 않습니다."
    assert 'rowIdPrefix: "jobRow-"' in src, (
        "행 안정 id 접두(jobRow-)가 사라졌습니다 — preserve.js 포커스 복원 계약 파손."
    )
    assert 'header: "문서"' in src, "선두 열 머리 「문서」(F33)가 config 에서 사라졌습니다."


def test_zone_dispatch_actions_single_sourced_in_factory():
    """데이터 존 디스패치 리터럴은 팩토리에만 — 소비 화면(job) 재중복 금지(가드 3, #94 동형)."""
    dz = DZ_JS.read_text(encoding="utf-8")
    for action in ZONE_ACTIONS:
        needle = f'"{action}"'
        assert needle in dz, f"팩토리에 {needle} 디스패치가 없습니다 — 이동이 덜 됐습니다."
        for consumer in (JOB_JS,):
            assert needle not in consumer.read_text(encoding="utf-8"), (
                f"{consumer.name} 에 {needle} 디스패치가 남아/되살아 있습니다 — 데이터 존 "
                "사본 재유입(#94 중복 클래스 동형). datazone.js 단일 출처를 유지하세요."
            )


# (test_draft_session_consumes_factory_with_queue_identity ·
#  test_draft_session_keys_use_source_identity_not_label 삭제 — 소비자가 하나(job)로
#  수렴해 두-소비자 접두 격리·기안 세션 키의 대상이 없다, F6 PR-B. 화면 불가지 계약
#  자체는 test_factory_is_screen_agnostic 이 계속 진다.)


def test_factory_is_screen_agnostic():
    """팩토리에 job 고유 id·화면 루트 하드코딩 금지(가드 4) — 전부 config 주입이어야 한다.

    ``jobXxx`` id 리터럴이 하나라도 박히면 PR-2b(txt 큐)의 두 번째 인스턴스가 숨은 「작업」
    화면 DOM 을 조용히 만진다(getElementById 는 화면 은닉과 무관하게 해소 — poolList 전례).
    """
    dz = _strip_js_comments(DZ_JS.read_text(encoding="utf-8"))
    hits = re.findall(r"""["'#]job[A-Z][A-Za-z]*|scr-job""", dz)
    assert not hits, f"datazone.js 에 job 고유 식별자가 하드코딩됐습니다: {sorted(set(hits))}"


def test_popover_dismiss_mechanism_single_sourced():
    """팝오버 바깥-닫기 기제는 popover.js 단일 출처(가드 5, PR 리뷰) — 사본 재유입 금지.

    기제(인스턴스별 suppress 플래그·캡처 단계 클릭 1회 소비·pointerdown 바깥 닫기·Escape)는
    Popover.wireDismiss 만 소유한다. 메뉴(job.js)·열 패널(datazone.js)은 각자 술어만 주입 —
    양 표면이 손수 판을 되살리면(이 PR 이전 형태) 한쪽 수정이 다른 쪽에 미러링되지 않는
    드리프트 클래스가 재개된다. 바깥 pointerdown 닫기의 실 거동은 실앱 게이트
    ``menu_closed`` 프로브가 되읽는다.
    """
    pop = POPOVER_JS.read_text(encoding="utf-8")
    assert "export const Popover" in pop and "function wireDismiss(" in pop, (
        "popover.js 가 Popover.wireDismiss 를 노출하지 않습니다."
    )
    assert "let suppressNextClick" in pop, "popover.js 가 인스턴스별 suppress 플래그를 잃었습니다."
    for needle, what in (
        (r'addEventListener\("click",[\s\S]{0,200}?suppressNextClick', "캡처 클릭 소비자"),
        (r'addEventListener\("pointerdown",', "바깥 pointerdown 닫기"),
        (r'addEventListener\("keydown",[\s\S]{0,120}?Escape', "Escape 닫기"),
    ):
        assert re.search(needle, pop), f"popover.js 에 {what}가 없습니다."
    # 두 표면은 헬퍼 소비만 — 손수 판(자기 suppress 플래그) 재유입 금지(주석 제외).
    # ⋮ 메뉴 소비처는 「문서 작업」 라이브러리로 옮겼다(F2 PR-B) — 기제는 한 벌 그대로.
    for path, owner in ((LIB_JS, "행/그룹 ⋮ 메뉴"), (DZ_JS, "열 필터 패널")):
        src = _strip_js_comments(path.read_text(encoding="utf-8"))
        assert "Popover.wireDismiss({" in src, (
            f"{path.name} 이 Popover.wireDismiss 를 소비하지 않습니다({owner} 몫)."
        )
        assert "suppressNextClick" not in src, (
            f"{path.name} 에 손수 판 suppress 상태가 재유입됐습니다 — popover.js 단일 출처 위반."
        )


def test_factory_snapshot_observed_unconditionally():
    """팩토리 LAST 관측(dz.sync)은 존 렌더 게이트와 무관하게 무조건이어야 한다(가드 6).

    빠지면 has_job=false push(작업 제거 등) 뒤 팩토리가 직전 세션의 has_data=true 스냅샷을
    보유한 채 flushPendingSearch 가 죽은 세션에 filter_search 를 디스패치한다(PR 리뷰 —
    master 의 무조건 ``LAST = s`` 계약 복원).
    """
    dz = DZ_JS.read_text(encoding="utf-8")
    assert "function sync(" in dz, "datazone.js 에 스냅샷 관측(sync)이 없습니다."
    assert re.search(r"return \{[^}]*\bsync\b", dz), "sync 가 팩토리 반환 API 에 없습니다."
    job = JOB_JS.read_text(encoding="utf-8")
    assert "dz.sync(s)" in job, "job.js 가 dz.sync 를 호출하지 않습니다 — stale LAST 오발 창."
    # 데이터-우선 전환(§18.2)으로 hasJob 렌더 게이트 자체가 사망 — 전 렌더러 무조건이라
    # "게이트 앞" 순서 단언은 좌표를 잃었다. 불변식의 정신(무조건 관측)은 재유입 가드로
    # 개정: dz.sync 가 hasJob 조건 블록 안으로 다시 들어가면 안 된다.
    import re as _re
    assert not _re.search(r"if\s*\(\s*hasJob\s*\)[\s\S]{0,300}dz\.sync", job), (
        "dz.sync 가 hasJob 게이트 안으로 강등됐습니다 — 무조건 관측 계약 위반(PR 리뷰)."
    )


def test_moved_surfaces_not_redefined_in_job():
    """이동한 렌더러·상태가 job.js 에 재정의되면 안 된다 — 두 벌 표면의 조용한 드리프트 금지."""
    job = JOB_JS.read_text(encoding="utf-8")
    for symbol in ("function renderTable(", "function renderChips(", "function renderStrip(",
                   "function openColPanel(", "function toggleRow(", "function segsHtml(",
                   "function flushPendingSearch("):
        assert symbol not in job, (
            f"job.js 에 {symbol} 이 재정의됐습니다 — datazone.js 팩토리 단일 출처 위반."
        )


def test_table_rows_keep_native_semantics_and_checkbox_in_lead_cell():
    """행은 row/aria-selected, 선택 의미는 선두 셀의 native checkbox가 소유한다."""
    src = DZ_JS.read_text(encoding="utf-8")
    css = app_css()
    assert 'aria-selected="${r.selected ? "true" : "false"}"' in src
    assert 'role="checkbox"' not in src
    assert '<td class="doccol"><div class="doccell"><input type="checkbox"' in src
    assert ".jobtb td.doccol{display:flex" not in css
    assert ".jobtb .doccell{display:flex" in css
    assert ".jobtb tbody tr.on{background:var(--a-sel)}" in css


def test_table_consumes_snapshot_column_kind_without_web_inference():
    """금액·날짜 조판은 Python의 column.kind만 소비하고 웹 판정기를 만들지 않는다."""
    src = DZ_JS.read_text(encoding="utf-8")
    css = app_css()
    assert 'class="col-${c.kind}"' in src
    assert "column.kind || \"text\"" in src
    assert ".jobtb .col-amount,.jobtb .col-date" in css
    assert "font-variant-numeric:tabular-nums" in css


def test_unselected_lead_guidance_is_single_sourced_in_headers():
    """비선택 placeholder는 행마다 반복하지 않고 공용 표 머리에서 한 번만 안내한다.

    (「큐」 힌트의 기안 몫은 화면과 함께 사망 — F6 PR-B. 남은 소비자는 job 하나다.)
    """
    job = _strip_js_comments(JOB_JS.read_text(encoding="utf-8"))
    assert 'hint: "선택하면 파일명이 정해집니다"' in job
    assert 'doc-off">선택하면 파일명이 정해집니다' not in job
    assert 'aria-hidden="true">—</span>' in job


def test_filter_roles_have_distinct_labels_and_surface_hierarchy():
    """정의·가지·관통 선택은 공용 렌더의 텍스트 라벨과 서로 다른 면을 함께 쓴다."""
    src = DZ_JS.read_text(encoding="utf-8")
    css = app_css()
    assert 'class="fchip definition"><span class="chip-role">필터</span>' in src
    assert 'class="fchip branch"><span class="chip-role">가지</span>' in src
    assert 'class="fchip selection"><span class="chip-role">선택</span>' in src
    assert ".fchip.definition{" in css and "var(--a-primary) 10%" in css
    assert ".fchip.branch{background:var(--n-surface-alt)" in css
    assert ".fchip.branch{border-style:dashed" not in css
    assert ".fstrip{border:1px solid var(--a-border)" in css
    assert ".filter-reapply{" in css


def test_session_change_drops_pending_column_text() -> None:
    """리뷰 4R P2 — 세션이 갈리면 대기 중 열 조건 **소재**도 함께 버린다.

    타이머만 끄고 소재를 남기면 나중 정산(`flushPendingEdits`)이 죽은 세션의 조건을 새
    세션에 보낸다 — 열이 남아 있으면 조용히 걸리고, 없으면 적용이 거절된다.
    """
    src = (SOURCE_JS_DIR / "datazone.js").read_text(encoding="utf-8")
    reset = src.split("clearTimeout(searchTimer); clearTimeout(colTextTimer);", 1)[1][:400]
    assert "colTextPending = null" in reset, "세션 전환이 대기 중 열 조건을 남깁니다."
