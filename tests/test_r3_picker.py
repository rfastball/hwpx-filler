"""데이터 선택 다이얼로그 정적 계약 — 구 pool_picker C8·K12 의 승계분(재작성 F1).

`pool_picker.js`(등록 데이터 겨눔 모달)와 `screens/pool.js`(데이터 관리 화면)는 사망하고
`data_picker.js` 한 면이 둘을 승계했다(지도 §10.7). 승계는 의무를 상속하므로, 그 두 표면이
값을 치르고 세운 계약을 이 파일이 새 표면에 그대로 요구한다:

C8(HIGH): 마운트 호출(``load_pool``)에 try/catch/finally 가 없으면 브리지 거절 1회로
``loading`` 이 영구 true 로 고착 — 이후 모든 클릭 무시(재시도 불가)·오류 무표시. 또한
백엔드 마운트는 화면 VM 을 즉시 갈아끼우므로 **중간 취소가 불가능**하다: 로드 중 닫기·
Escape 는 차단하고 그 사실을 표기한다('취소됐다'며 데이터가 바뀌는 조용한 거짓말 금지).

C5: 손상 격리(RC-05)는 목록과 **다른 컨테이너**에 상주해야 한다 — 상태줄(로드 오류 재진술)과
한 자리를 쓰면 회차마다 덮여 손상 데이터셋이 다시 무표시 증발한다.

K12: 모달 골격은 index.html 정적 소유여야 정적 파싱 가드(test_web_dom_contract)에 걸린다.

순수 JS 거동의 실행 검증은 selftest 게이트 몫(``data_picker`` 프로브) — 여기서는 정적
계약(소스 텍스트)만 단언한다.
"""
from __future__ import annotations

import re

from _web_source import SOURCE_INDEX, SOURCE_JS_DIR

WEB_INDEX = SOURCE_INDEX
PICKER_JS = SOURCE_JS_DIR / "data_picker.js"


def _picker_src() -> str:
    return PICKER_JS.read_text(encoding="utf-8")


def _index_src() -> str:
    return WEB_INDEX.read_text(encoding="utf-8")


def _segment(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


# ---------------------------------------------------------------- C8: loading 고착 봉합

def test_mount_call_is_guarded_by_try_finally():
    """마운트 호출이 try/catch/finally 안에 있고 finally 가 loading 을 해제해야 한다(C8).

    finally 없는 await 는 브리지 거절 1회로 loading 영구 고착 → 다이얼로그 전면 사망.
    """
    seg = _segment(_picker_src(), "async function mountPinned", "async function browseFile")
    assert '"load_pool"' in seg, "mountPinned 가 더 이상 load_pool 을 부르지 않습니다."
    assert "try {" in seg and "} catch" in seg and "} finally {" in seg, (
        "마운트 호출이 try/catch/finally 로 감싸져 있지 않습니다 — 거절 시 loading 고착(C8)."
    )
    tail = seg[seg.index("} finally {"):]
    assert re.search(r"loading\s*=\s*false", tail), (
        "finally 블록이 loading 을 해제하지 않습니다 — 거절 경로에서 클릭 영구 무시(C8)."
    )
    catch_body = seg[seg.index("} catch"):seg.index("} finally {")]
    assert "setStatus(" in catch_body, (
        "catch 블록이 오류를 면 안 상태줄에 표면화하지 않습니다 — 조용한 삼킴(C8)."
    )
    # 실패는 면을 닫지 않는다(계약면 4) — 성사(finish)는 ok 경로에만 있다.
    fail_paths = seg[seg.index("setStatus(\"⚠ "):]
    assert "finish(" not in fail_paths, (
        "실패 경로가 면을 닫습니다 — 사용자가 문맥을 잃고 재선택도 못 합니다(계약면 4)."
    )


def test_escape_and_close_are_blocked_while_loading():
    """로드 중 Escape·닫기 버튼이 닫힘 대신 차단+표기로 귀결돼야 한다(C8 후반부)."""
    src = _picker_src()
    assert re.search(r'e\.key\s*===\s*"Escape"\s*&&\s*loading', src), (
        "로드 중 Escape 를 가드하는 분기가 없습니다 — 로드 중 '가짜 취소' 재발(C8)."
    )
    assert "stopImmediatePropagation" in src, (
        "Escape 차단이 stopImmediatePropagation 없이 이뤄집니다 — Modal 캡처 핸들러가 "
        "여전히 모달을 닫아 가짜 취소가 됩니다(C8)."
    )
    # 캡처 리스너는 Modal.open 보다 먼저 등록돼야 선행 수신한다(같은 대상 캡처는 등록 순).
    add_pos = src.find('document.addEventListener("keydown", onEscCapture, true)')
    open_pos = src.find('Modal.open("dataPickerModal"')
    assert 0 <= add_pos < open_pos, (
        "onEscCapture 등록이 Modal.open 보다 뒤에 있습니다 — Modal 이 먼저 받아 닫아버려 "
        "로드 중 Escape 차단이 무력화됩니다(C8)."
    )
    # 닫기 버튼도 loading 가드를 태워야 한다(닫힘=onClose=취소 경로 봉쇄).
    m = re.search(
        r'\$\("dataPickerClose"\)\.addEventListener\("click",\s*\(\)\s*=>\s*\{(?P<body>.*?)\n    \}\)',
        src,
        re.S,
    )
    assert m, "닫기 버튼 배선이 사라졌습니다 — 면을 닫을 길이 없습니다."
    assert re.search(r"if\s*\(loading\)", m.group("body")), (
        "닫기 버튼 핸들러에 loading 가드가 없습니다 — 로드 중 클릭이 가짜 취소로 귀결(C8)."
    )
    assert "noteLoadingBlock" in src and "닫을 수 없습니다" in src, (
        "로드 중 닫기 차단 사실을 표기하는 문구/함수가 없습니다 — 조용한 무시(C8)."
    )


# ---------------------------------------------------------------- C5: 손상 격리 소비측

def test_corrupted_rows_are_consumed_and_rendered_separately():
    """스냅샷 ``corrupted`` 를 읽어 **상태줄과 다른 자리**에 상주 렌더해야 한다(C5 소비측).

    백엔드가 손상을 격리 수집해 실어도 표면이 ``rows`` 만 소비하면 손상 데이터셋은 여전히
    무표시 증발한다 — 조용한 드롭이 UI 층으로 이동만 한 것이다.
    """
    src = _picker_src()
    assert re.search(r"LAST\s*&&\s*LAST\.corrupted", src), (
        "data_picker.js 가 pool 스냅샷의 corrupted 를 읽지 않습니다 — 손상 무표시 증발(C5)."
    )
    seg = _segment(src, "function renderCorrupt", "function renderAll")
    assert "esc(c.file)" in seg and "esc(c.error)" in seg, (
        "손상 행의 파일명·오류가 escHtml 을 태워 렌더되지 않습니다(C5 소비측)."
    )
    assert 'dataPickerCorrupt' in seg and 'dataPickerNote' not in seg, (
        "손상 표지가 상태줄(#dataPickerNote)과 자리를 공유합니다 — 로드 오류 문구에 덮여 "
        "다시 증발합니다(C5 소비측)."
    )


# ---------------------------------------------------------------- K12: 정적 골격 소유

def test_picker_skeleton_is_static_in_index_html():
    """다이얼로그 골격이 index.html 에 정적으로 존재해야 한다(K12 — 동적 생성 사각 봉합).

    role/aria-modal/aria-labelledby 정합은 test_web_dom_contract 의 MODAL_LABELLEDBY 가
    가드한다 — 여기선 모듈이 참조하는 내부 id 들의 존재를 단언한다.
    """
    index = _index_src()
    assert 'id="dataPickerModal"' in index, (
        "dataPickerModal 정적 골격이 index.html 에 없습니다 — DOM 계약 가드 사각(K12)."
    )
    for inner in (
        "dataPickerTitle", "dataPickerNote", "dataPickerCurrent", "dataPickerPinned",
        # (dataPickerRefresh 는 U2 §2.3 에서 사망 — open() 이 여는 순간 재스캔하므로 상시
        #  버튼이 잉여였다. 그 부재는 test_r3_pool 이 단언한다.
        #  dataPickerRegister 는 U2 §2.7 4행에서 사망 — 부재 단언은 아래
        #  test_direct_register_is_dead.)
        "dataPickerCorrupt", "dataPickerBrowse",
        # 같은 데이터 등록 2+건의 병합 표면(#347 — §5.3 구판 마이그레이션 loud 경로).
        "dataPickerDupes",
        "dataPickerClose",
    ):
        assert f'id="{inner}"' in index, (
            f"다이얼로그 내부 요소 id='{inner}' 가 index.html 에 없습니다(K12)."
        )
    # 골격은 정적 소유다 — 모듈이 다시 만들어 내면 정적 파싱 가드가 무력해진다.
    assert "createElement" not in _picker_src(), (
        "data_picker.js 가 골격을 동적 생성합니다 — 정적 DOM 계약 사각 재발(K12)."
    )


def test_direct_register_is_dead():
    """「＋ 직접 등록…」(#dataPickerRegister)은 DOM·배선 모두 소멸해야 한다(U2 §2.7 4행).

    유일한 고유 기능(마운트하지 않고 등록)이 가능한 이유가 곧 결함(경로만 반환하고 읽지
    않음)이었다 — 대체 경로 신설 없이 삭제됐고, 등록 진입은 「이 데이터 고정」(pin)·
    「다시 연결」(relink) 둘뿐이다. 캡션의 .acts span 도 §2.3 새로고침 제거와 합쳐져
    통째로 비었으므로 함께 죽었다.
    """
    assert "dataPickerRegister" not in _index_src(), (
        "「＋ 직접 등록…」 버튼 DOM 이 index.html 에 남아 있습니다(U2 §2.7 4행)."
    )
    assert "dataPickerRegister" not in _picker_src(), (
        "「＋ 직접 등록…」 배선이 data_picker.js 에 남아 있습니다(U2 §2.7 4행)."
    )
    # 의무 상속분: relink 가 등록 모달의 찾아보기(#poolRegBrowse)를 쓰므로 브리지·버튼은
    # 살되 pin 모드에서만 감춘다 — 감춤 배선의 존재를 함께 단언한다(§2.7 5행).
    src = _picker_src()
    assert "poolRegBrowse" in src and 'readOnly' in src, (
        "pin 모드의 path·sheet 읽기전용/찾아보기 감춤 배선이 없습니다(U2 §2.7 5행)."
    )


def test_picker_enrolled_in_dom_contract():
    """dataPickerModal 이 test_web_dom_contract 의 MODAL_LABELLEDBY 에 편입돼 있어야 한다(K12)."""
    import test_web_dom_contract as dom  # 같은 tests/ 디렉터리(rootdir 기반 임포트)

    assert dom.MODAL_LABELLEDBY.get("dataPickerModal") == "dataPickerTitle", (
        "dataPickerModal 이 DOM 계약 테스트(MODAL_LABELLEDBY)에서 빠졌습니다 — "
        "role/aria 가드 사각 재발(K12)."
    )


def test_wiring_happens_once():
    """배선은 1회 가드 안에서 — 다이얼로그를 여러 번 열어도 리스너가 중복되지 않는다(K12).

    구 build() 의 ``wired`` 가드 승계: 리스너가 겹치면 한 번의 클릭이 두 왕복을 만든다
    (삭제 확인 2연발 등 파괴 경로에서 특히 나쁘다).
    """
    src = _picker_src()
    assert re.search(r"if\s*\(wired\)\s*return;", src), (
        "배선 1회 가드(wired)가 사라졌습니다 — 재호출 시 리스너 중복(K12)."
    )


def test_picker_header_describes_delivered_ownership():
    """헤더가 정적 골격 소유와 승계 경계를 기술해야 한다(주석-코드 정합)."""
    header = _picker_src().split("(function", 1)[0]
    assert "index.html" in header or "정적" in header, (
        "data_picker.js 헤더가 골격 소유를 기술하지 않습니다(K12)."
    )
    assert "PoolController" in header, (
        "data_picker.js 헤더가 목록·수명 관리의 백엔드 소유자를 기술하지 않습니다 — "
        "표면이 판정을 재구현했다는 오해를 남깁니다."
    )
