"""데이터 존 공용 팩토리(슬라이스 6 PR-2a) 정적 가드 — job.js 추출의 단일 출처·분리 계약.

「작업」 화면의 데이터 존 ~450줄(열 필터 패널·필터 테이블/Shift 선택·칩 줄·필터 밖 선택
스트립·자모 하이라이트 세그먼트)을 ``web/js/datazone.js`` 의 ``DataZone.create(config)``
팩토리로 추출했다(#90 착지 6 — 기안 일괄 큐가 같은 표면을 재사용). 이 모듈은
추출이 조용히 되감기는 회귀를 정적으로 차단한다:

1. 팩토리 존재·로드 순서(esc.js < datazone.js < screens/job.js).
2. job.js 가 실제로 소비(DataZone.create) — 정의 삭제만 하고 미배선 방지.
3. 데이터 존 디스패치 리터럴의 단일 출처 — job.js 재중복은 #94(링2 400줄 중복)와 동형의
   결함 클래스라 팩토리에만 있어야 한다.
4. 화면 불가지 — 팩토리에 job 고유 id(``jobXxx``)·화면 루트가 하드코딩되면 PR-2b 의 두 번째
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
WEB_INDEX = WEB / "index.html"
DZ_JS = WEB / "js" / "datazone.js"
POPOVER_JS = WEB / "js" / "popover.js"
JOB_JS = WEB / "js" / "screens" / "job.js"
SESSION_JS = WEB / "js" / "draftsession.js"  # 기안 세션 표면(두 번째 인스턴스 생성처, #148 3a)
DRAFT_JS = WEB / "js" / "screens" / "draft.js"  # 「기안」 화면(세션 id 맵 — 구 txt 흡수, 슬라이스 6)

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
    assert "window.DataZone" in src, "datazone.js 가 window.DataZone 을 노출하지 않습니다."
    assert "function create(cfg)" in src, "DataZone 팩토리(create)가 없습니다."


def test_load_order_esc_then_shared_then_screens():
    """로드 순서 — esc.js < popover.js·datazone.js < 소비 화면(job·기안) (미정의 시점 참조 방지).

    기안 소비는 draft.js 가 트리거한다: DataZone.create 는 draftsession.js 팩토리 create() 안에서
    불리고, 그 create() 는 draft.js 가 module-eval 에 window.DraftSession.create({...}) 로 부른다 —
    그때 window.DataZone 이 있어야 한다(구 txt.js 소비자는 슬라이스 6 삭제).
    """
    index = WEB_INDEX.read_text(encoding="utf-8")
    consumers = ('src="js/screens/job.js"', 'src="js/screens/draft.js"')
    for needle in ('src="js/esc.js"', 'src="js/popover.js"', 'src="js/datazone.js"',
                   *consumers):
        assert needle in index, f"{needle} 가 index.html 에 없습니다."
    esc_pos = index.index('src="js/esc.js"')
    first_consumer = min(index.index(c) for c in consumers)
    for shared in ('src="js/popover.js"', 'src="js/datazone.js"'):
        assert esc_pos < index.index(shared) < first_consumer, (
            f"로드 순서가 esc.js → {shared} → 소비 화면(job·기안)이 아닙니다."
        )


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
    """데이터 존 디스패치 리터럴은 팩토리에만 — 소비 화면(job·기안) 재중복 금지(가드 3, #94 동형)."""
    dz = DZ_JS.read_text(encoding="utf-8")
    for action in ZONE_ACTIONS:
        needle = f'"{action}"'
        assert needle in dz, f"팩토리에 {needle} 디스패치가 없습니다 — 이동이 덜 됐습니다."
        for consumer in (JOB_JS, SESSION_JS, DRAFT_JS):
            assert needle not in consumer.read_text(encoding="utf-8"), (
                f"{consumer.name} 에 {needle} 디스패치가 남아/되살아 있습니다 — 데이터 존 "
                "사본 재유입(#94 중복 클래스 동형). datazone.js 단일 출처를 유지하세요."
            )


def test_draft_session_consumes_factory_with_queue_identity():
    """기안 세션 표면이 데이터 존 인스턴스를 소비한다 — 큐 표지 + 화면별 행 id 접두.

    세션 표면은 공용 팩토리(draftsession.js) 소유이고, **화면 고유값은 소비 화면이 준다**:
    rowIdPrefix 는 전역 id 유일성(preserve.js 복원 계약)의 화면 몫이라 두 소비 화면(job·기안)이
    서로 갈라져야 한다(jobRow- vs draftRow-). 선두 열 「큐」는 전-선언 큐 표지(블록 3 결정 16)의 표면.
    (구 「기안문 채우기」 표면은 슬라이스 6 에서 삭제 — 이제 기안 세션 소비 화면은 draft.js 하나다.)
    """
    src = SESSION_JS.read_text(encoding="utf-8")
    assert "DataZone.create({" in src, "기안 세션 팩토리가 DataZone.create 를 소비하지 않습니다."
    assert 'header: "큐"' in src, "선두 열 머리 「큐」(전-선언 표지)가 config 에서 사라졌습니다."
    assert "flushPendingSearch" in src, (
        "데이터 재선택 전 검색 정산(flushPendingSearch)이 사라졌습니다 — 직전 필터 슬롯에 "
        "마지막 타이핑이 실리지 않습니다(결정 28)."
    )
    prefixes = {}
    for name, path in (("job", JOB_JS), ("draft", DRAFT_JS)):
        csrc = path.read_text(encoding="utf-8")
        m = re.search(r'rowIdPrefix:\s*"([^"]+)"', csrc)
        assert m, f"{name} 화면이 행 안정 id 접두를 주지 않습니다 — 포커스 복원 대상 충돌."
        prefixes[name] = m.group(1)
    assert prefixes["job"] != prefixes["draft"], (
        f"두 데이터 존 소비 화면의 행 id 접두가 같습니다({prefixes!r}) — 전역 유일성 파손(preserve.js)."
    )


def test_draft_session_keys_use_source_identity_not_label():
    """기안 세션 지문·고지 키는 **정체**(data_key)여야 한다 — 표시 라벨(basename) 금지(리뷰).

    라벨은 ``folder1/명단.xlsx``↔``folder2/명단.xlsx`` 가 같은 문자열이라, 라벨로 겨누면
    동명 다른 폴더 전환에서 세션 리셋(Shift 앵커·검색 디바운스·존 고지)이 발화하지 않고
    이전 파일의 앵커가 살아남아 새 파일에서 엉뚱한 범위가 조용히 선택된다.
    """
    src = _strip_js_comments(SESSION_JS.read_text(encoding="utf-8"))
    assert "tableKey: (s) => s.data_key" in src, (
        "기안 세션 tableKey 가 소스 정체(data_key)를 쓰지 않습니다 — 동명 파일 전환에 stale 앵커."
    )
    # 존 고지 키도 같은 정체에 겨눈다(라벨이면 동명 전환에 이전 고지가 남는다). 표시 라벨
    # 자체의 소비(#draftDataLabel 채우기)는 정당하므로 **키 대입만** 본다.
    assert re.search(r"zkey\s*=\s*s\.data_key", src), (
        "존 고지 키(zoneNoteKey)가 소스 정체를 쓰지 않습니다 — 동명 전환에 고지 잔존."
    )
    assert not re.search(r"(tableKey|zkey)\s*[:=][^\n]*data_source_label", src), (
        "표시 라벨을 세션 키로 쓰는 코드가 남아 있습니다(basename 동명 충돌)."
    )


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
    assert "window.Popover" in pop and "function wireDismiss(" in pop, (
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
    for path, owner in ((JOB_JS, "행/그룹 ⋮ 메뉴"), (DZ_JS, "열 필터 패널")):
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
    # sync 는 hasJob 게이트 **앞**(무조건 경로)에 있어야 한다 — 렌더 호출로의 강등 금지.
    assert job.index("dz.sync(s)") < job.index("if (hasJob)"), (
        "dz.sync 가 hasJob 게이트 뒤로 밀렸습니다 — 무조건 관측 계약 위반(PR 리뷰)."
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
    css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
    assert 'aria-selected="${r.selected ? "true" : "false"}"' in src
    assert 'role="checkbox"' not in src
    assert '<td class="doccol"><div class="doccell"><input type="checkbox"' in src
    assert ".jobtb td.doccol{display:flex" not in css
    assert ".jobtb .doccell{display:flex" in css
    assert ".jobtb tbody tr.on{background:var(--a-sel)}" in css


def test_table_consumes_snapshot_column_kind_without_web_inference():
    """금액·날짜 조판은 Python의 column.kind만 소비하고 웹 판정기를 만들지 않는다."""
    src = DZ_JS.read_text(encoding="utf-8")
    css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
    assert 'class="col-${c.kind}"' in src
    assert "column.kind || \"text\"" in src
    assert ".jobtb .col-amount,.jobtb .col-date" in css
    assert "font-variant-numeric:tabular-nums" in css


def test_unselected_lead_guidance_is_single_sourced_in_headers():
    """비선택 placeholder는 행마다 반복하지 않고 각 공용 표 머리에서 한 번만 안내한다."""
    job = _strip_js_comments(JOB_JS.read_text(encoding="utf-8"))
    draft = _strip_js_comments(SESSION_JS.read_text(encoding="utf-8"))
    assert 'hint: "선택하면 파일명이 정해집니다"' in job
    assert 'hint: "선택하면 큐에 담깁니다"' in draft
    assert 'doc-off">선택하면 파일명이 정해집니다' not in job
    assert 'doc-off">선택하면 큐에 담깁니다' not in draft
    assert 'aria-hidden="true">—</span>' in job
    assert 'aria-hidden="true">—</span>' in draft
