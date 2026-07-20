"""데이터 존 공용 팩토리(슬라이스 6 PR-2a) 정적 가드 — job.js 추출의 단일 출처·분리 계약.

「작업」 화면의 데이터 존 ~450줄(열 필터 패널·필터 테이블/Shift 선택·칩 줄·필터 밖 선택
스트립·자모 하이라이트 세그먼트)을 ``web/js/datazone.js`` 의 ``DataZone.create(config)``
팩토리로 추출했다(#90 착지 6 — PR-2b 에서 txt 일괄 큐가 같은 표면을 재사용). 이 모듈은
추출이 조용히 되감기는 회귀를 정적으로 차단한다:

1. 팩토리 존재·로드 순서(esc.js < datazone.js < screens/job.js).
2. job.js 가 실제로 소비(DataZone.create) — 정의 삭제만 하고 미배선 방지.
3. 데이터 존 디스패치 리터럴의 단일 출처 — job.js 재중복은 #94(링2 400줄 중복)와 동형의
   결함 클래스라 팩토리에만 있어야 한다.
4. 화면 불가지 — 팩토리에 job 고유 id(``jobXxx``)·화면 루트가 하드코딩되면 PR-2b 의 두 번째
   인스턴스가 조용히 첫 화면 DOM 을 만진다(getElementById 는 숨은 화면으로도 해소된다).
5. 문서 레벨 리스너·suppressNextClick 분리 — 메뉴(화면 몫)와 열 패널(팩토리 몫)이 각자
   상태로 소비한다(공유 플래그의 교차 소거 금지).

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
JOB_JS = WEB / "js" / "screens" / "job.js"

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


def test_load_order_esc_then_datazone_then_job():
    """로드 순서 — esc.js < datazone.js < screens/job.js (미정의 시점 참조 방지, 가드 1)."""
    index = WEB_INDEX.read_text(encoding="utf-8")
    for needle in ('src="js/esc.js"', 'src="js/datazone.js"', 'src="js/screens/job.js"'):
        assert needle in index, f"{needle} 가 index.html 에 없습니다."
    assert index.index('src="js/esc.js"') < index.index('src="js/datazone.js"') < index.index(
        'src="js/screens/job.js"'
    ), "로드 순서가 esc.js → datazone.js → screens/job.js 가 아닙니다."


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
    """데이터 존 디스패치 리터럴은 팩토리에만 — job.js 재중복 재유입 금지(가드 3, #94 동형)."""
    dz = DZ_JS.read_text(encoding="utf-8")
    job = JOB_JS.read_text(encoding="utf-8")
    for action in ZONE_ACTIONS:
        needle = f'"{action}"'
        assert needle in dz, f"팩토리에 {needle} 디스패치가 없습니다 — 이동이 덜 됐습니다."
        assert needle not in job, (
            f"job.js 에 {needle} 디스패치가 남아/되살아 있습니다 — 데이터 존 사본 재유입"
            "(#94 중복 클래스 동형). datazone.js 단일 출처를 유지하세요."
        )


def test_factory_is_screen_agnostic():
    """팩토리에 job 고유 id·화면 루트 하드코딩 금지(가드 4) — 전부 config 주입이어야 한다.

    ``jobXxx`` id 리터럴이 하나라도 박히면 PR-2b(txt 큐)의 두 번째 인스턴스가 숨은 「작업」
    화면 DOM 을 조용히 만진다(getElementById 는 화면 은닉과 무관하게 해소 — poolList 전례).
    """
    dz = _strip_js_comments(DZ_JS.read_text(encoding="utf-8"))
    hits = re.findall(r"""["'#]job[A-Z][A-Za-z]*|scr-job""", dz)
    assert not hits, f"datazone.js 에 job 고유 식별자가 하드코딩됐습니다: {sorted(set(hits))}"


def test_click_suppression_state_is_owned_per_surface():
    """suppressNextClick 은 표면별 소유(가드 5) — 메뉴(job.js)·열 패널(팩토리) 각자 선언·소비.

    한쪽이 자기 선언을 잃고 상대 상태를 참조하면(전역 승격 등) 교차 소거가 생긴다: 메뉴
    닫기 클릭이 패널 몫 소비를 지우고 행 토글로 새는 류. 각 파일이 자기 ``let`` 선언과
    캡처 단계 소비자를 유지해야 한다.
    """
    for path, owner in ((JOB_JS, "행/그룹 ⋮ 메뉴"), (DZ_JS, "열 필터 패널")):
        src = path.read_text(encoding="utf-8")
        assert "let suppressNextClick = false" in src, (
            f"{path.name} 이 자기 suppressNextClick 선언을 잃었습니다({owner} 몫)."
        )
        assert re.search(r'addEventListener\("click",[\s\S]{0,200}?suppressNextClick', src), (
            f"{path.name} 에 캡처 단계 클릭 소비자가 없습니다({owner} 몫)."
        )
    # 문서 레벨 pointerdown/keydown 도 각자 등록 — 메뉴 몫이 팩토리 이동에 휩쓸려 미배선되면
    # 바깥 클릭/Escape 닫기가 조용히 죽는다(이번 추출에서 실제로 났던 봉합 누락).
    job = JOB_JS.read_text(encoding="utf-8")
    dz = DZ_JS.read_text(encoding="utf-8")
    for src, name in ((job, "job.js"), (dz, "datazone.js")):
        assert 'addEventListener("pointerdown", onDocPointerDown)' in src, (
            f"{name} 의 문서 레벨 pointerdown(바깥 클릭 닫기)이 미배선입니다."
        )
        assert 'addEventListener("keydown", onDocKeydown)' in src, (
            f"{name} 의 문서 레벨 keydown(Escape 닫기)이 미배선입니다."
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
