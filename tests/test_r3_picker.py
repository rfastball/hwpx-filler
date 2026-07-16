"""코드리뷰 3차(picker 클러스터) 회귀 가드 — pool_picker C8·K12.

C8(HIGH): onPick 의 ``await Bridge.call(..., "load_pool", ...)`` 에 try/catch/finally 가 없어
브리지 거절 시 ``loading`` 이 영구 true 로 고착 — 이후 모든 클릭 무시(재시도 불가)·오류
무표시였다. catch 로 #poolNote 에 시끄럽게 재진술하고 finally 로 loading 을 해제한다.
추가로 로드 중 Escape 는 '취소(null)'로 해소되지만 백엔드 load_pool 은 화면 VM 을 이미
갈아끼운다 — 중간 취소가 불가능한 호출이므로 로드 중 취소·Escape 를 **차단하고 그 사실을
표기**하는 쪽을 택했다(confirm-or-alarm: '취소됐다'며 데이터가 바뀌는 조용한 거짓말 금지).

K12: poolModal 이 첫 사용 시 동적 생성이라 index.html 정적 파싱 가드(test_web_dom_contract)의
사각지대였다 — 골격을 index.html 로 이관하고 MODAL_LABELLEDBY 에 편입했다(role/aria 는 거기서
가드). 여기서는 이관 자체의 계약(정적 골격 존재·build() 의 취소 배선이 생성 분기 밖)을 가드한다.

순수 JS 거동이라 실행 검증은 selftest 게이트 몫 — 여기서는 정적 계약(소스 텍스트)만 단언한다.
"""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
WEB_INDEX = WEB / "index.html"
PICKER_JS = WEB / "js" / "pool_picker.js"


def _picker_src() -> str:
    return PICKER_JS.read_text(encoding="utf-8")


def _index_src() -> str:
    return WEB_INDEX.read_text(encoding="utf-8")


# ---------------------------------------------------------------- C8: loading 고착 봉합

def test_load_pool_call_is_guarded_by_try_finally():
    """load_pool 호출이 try/catch/finally 안에 있고 finally 가 loading 을 해제해야 한다(C8).

    finally 없는 await 는 브리지 거절 1회로 loading 영구 고착 → 피커 전면 사망(클릭 무시).
    """
    src = _picker_src()
    # load_pool 호출에 앵커한다 — 파일에는 pool_sources 용 try/catch(무 finally)도 있어
    # 느슨한 try…finally 탐색은 엉뚱한 블록에 걸린다. 인자 객체({ name: … })의 중첩 중괄호는
    # \{[^{}]*\} 로 명시 처리하고, catch/finally 본문은 중괄호 없음을 전제로 정밀 캡처.
    m = re.search(
        r"try\s*\{[^{}]*Bridge\.call\(screen,\s*\"load_pool\",\s*\{[^{}]*\}\)[^{}]*\}\s*"
        r"catch\s*\(\w+\)\s*\{(?P<catch>[^{}]*)\}\s*"
        r"finally\s*\{(?P<finally>[^{}]*)\}",
        src,
        re.S,
    )
    assert m, (
        "pool_picker.js 의 load_pool 호출이 try/catch/finally 로 감싸져 있지 않습니다 — "
        "브리지 거절 시 loading 영구 고착(C8)."
    )
    assert re.search(r"loading\s*=\s*false", m.group("finally")), (
        "finally 블록이 loading 을 해제하지 않습니다 — 거절 경로에서 클릭 영구 무시(C8)."
    )
    # catch 가 조용히 삼키지 않고 #poolNote 에 표면화해야 한다(confirm-or-alarm).
    assert "note" in m.group("catch") and "block" in m.group("catch"), (
        "catch 블록이 오류를 #poolNote 에 표면화하지 않습니다 — 조용한 삼킴(C8)."
    )


def test_escape_and_cancel_are_blocked_while_loading():
    """로드 중 Escape·취소 버튼이 닫힘 대신 차단+표기로 귀결돼야 한다(C8 후반부).

    load_pool 은 백엔드 VM 을 즉시 바꾸므로 중간 취소가 불가능 — 취소를 허용하면
    '취소됐는데 화면 데이터가 바뀌는' 조용한 거짓말이 된다. 차단 사실은 노트로 표기한다.
    """
    src = _picker_src()
    # Escape: loading 가드 + 전파 차단(Modal 의 캡처 닫힘 핸들러까지 끊는다).
    assert re.search(r'e\.key\s*===\s*"Escape"\s*&&\s*loading', src), (
        "로드 중 Escape 를 가드하는 분기가 없습니다 — 로드 중 '가짜 취소' 재발(C8)."
    )
    assert "stopImmediatePropagation" in src, (
        "Escape 차단이 stopImmediatePropagation 없이 이뤄집니다 — Modal 캡처 핸들러가 "
        "여전히 모달을 닫아 가짜 취소가 됩니다(C8)."
    )
    # 캡처 리스너는 Modal.open 보다 먼저 등록돼야 선행 수신한다(같은 대상 캡처는 등록 순).
    add_pos = src.find('document.addEventListener("keydown", onEscCapture, true)')
    open_pos = src.find('Modal.open("poolModal"')
    assert 0 <= add_pos < open_pos, (
        "onEscCapture 등록이 Modal.open 보다 뒤에 있습니다 — Modal 이 먼저 받아 닫아버려 "
        "로드 중 Escape 차단이 무력화됩니다(C8)."
    )
    # 취소 버튼도 loading 가드를 태워야 한다(닫힘=onClose=취소 경로 봉쇄).
    m = re.search(
        r'\$\("poolCancel"\)\.addEventListener\("click",\s*\(\)\s*=>\s*\{(?P<body>.*?)\}\s*\)',
        src,
        re.S,
    )
    assert m, "취소 버튼 배선이 사라졌습니다 — 취소 버튼이 죽습니다(K12/C8)."
    assert re.search(r"if\s*\(loading\)", m.group("body")), (
        "취소 버튼 핸들러에 loading 가드가 없습니다 — 로드 중 클릭이 가짜 취소로 귀결(C8)."
    )
    # 차단 사실의 시끄러운 표기(조용한 무시 금지).
    assert "noteLoadingBlock" in src and "취소할 수 없습니다" in src, (
        "로드 중 취소 차단 사실을 표기하는 문구/함수가 없습니다 — 조용한 무시(C8)."
    )


# ---------------------------------------------------------------- C5: 손상 병기 소비측

def test_corrupted_note_is_consumed_and_rendered():
    """choose() 가 백엔드 corrupted_note 를 읽어 escHtml 로 목록에 렌더해야 한다(C5 소비측).

    pool_sources_payload 가 손상 병기 문구를 실어도 피커가 res.items 만 소비하면 손상
    데이터셋은 겨눔 피커에서 여전히 무표시 증발한다 — 백엔드 계약 필드가 테스트에서만
    관측되는 반쪽 이행(조용한 드롭이 UI 층으로 이동만 한 것). 여기서 소비 계약을 가드한다.
    """
    src = _picker_src()
    # 페이로드 필드를 실제로 읽는다(items 만 소비 금지).
    assert re.search(r"res\s*&&\s*res\.corrupted_note", src), (
        "pool_picker.js 가 pool_sources 응답의 corrupted_note 를 읽지 않습니다 — "
        "손상 데이터셋이 피커에서 무표시 증발(C5 소비측)."
    )
    # 사용자 유래 문구는 escHtml 을 태워 렌더된다(innerHTML 조립 계약).
    assert re.search(r"escHtml\(corrupted\)", src), (
        "corrupted_note 가 escHtml 없이(또는 아예) 렌더되지 않습니다(C5 소비측)."
    )
    # 상주 렌더 위치는 목록(#poolPickList) 조립부 — #poolNote 는 로드 오류 재진술과
    # 공유돼 회차 리셋·오류 문구에 덮이므로 손상 표지의 자리가 아니다.
    m = re.search(r"list\.innerHTML\s*=\s*(?P<body>.*?);", src, re.S)
    assert m and "corrupted" in m.group("body"), (
        "corrupted_note 가 목록 영역(list.innerHTML)에 상주 렌더되지 않습니다 — "
        "#poolNote 공유 시 오류 문구에 덮여 다시 증발합니다(C5 소비측)."
    )


# ---------------------------------------------------------------- K12: 정적 골격 이관

def test_pool_modal_skeleton_is_static_in_index_html():
    """poolModal 골격이 index.html 에 정적으로 존재해야 한다(K12 — 동적 생성 사각 봉합).

    role/aria-modal/aria-labelledby 정합은 test_web_dom_contract 의 MODAL_LABELLEDBY 가
    가드한다(poolModal 편입) — 여기선 피커가 참조하는 내부 id 들의 존재를 단언한다.
    """
    index = _index_src()
    assert 'id="poolModal"' in index, (
        "poolModal 정적 골격이 index.html 에 없습니다 — DOM 계약 가드 사각 재발(K12)."
    )
    for inner in ("poolTitle", "poolPickList", "poolNote", "poolCancel"):
        assert f'id="{inner}"' in index, (
            f"poolModal 내부 요소 id='{inner}' 가 index.html 에 없습니다(K12)."
        )
    # 피커 목록 id 는 데이터 관리 화면의 poolList 와 달라야 한다(충돌=피커 전면 사망).
    assert 'id="poolList"' in index, (
        "데이터 관리 화면의 poolList 가 사라졌습니다 — id 충돌 가드의 전제가 무너집니다."
    )


def test_pool_modal_enrolled_in_dom_contract():
    """poolModal 이 test_web_dom_contract 의 MODAL_LABELLEDBY 에 편입돼 있어야 한다(K12)."""
    import test_web_dom_contract as dom  # 같은 tests/ 디렉터리(rootdir 기반 임포트)

    assert dom.MODAL_LABELLEDBY.get("poolModal") == "poolTitle", (
        "poolModal 이 DOM 계약 테스트(MODAL_LABELLEDBY)에서 빠졌습니다 — "
        "role/aria 가드 사각 재발(K12)."
    )


def test_build_wires_cancel_outside_creation_branch():
    """build() 의 취소 배선이 '없으면 생성' 분기 밖(1회 배선 가드)에 있어야 한다(K12).

    과거 형태(``if ($("poolModal")) return;`` 뒤 배선)는 정적 골격 이관 시 조기 반환으로
    취소 버튼이 미배선 — 취소 버튼이 죽는 잠복 결함이었다. 조기 반환 패턴 재유입을 금지한다.
    """
    src = _picker_src()
    assert not re.search(r'if\s*\(\$\("poolModal"\)\)\s*return', src), (
        "build() 가 poolModal 존재 시 조기 반환합니다 — 정적 골격에서 취소 버튼 미배선(K12)."
    )
    # 생성은 부재 시에만(정적 골격 재사용), 배선은 1회 가드로 별도 수행.
    assert re.search(r'if\s*\(!\$\("poolModal"\)\)', src), (
        "정적 골격 재사용 분기(if (!$(\"poolModal\")))가 사라졌습니다(K12)."
    )
    assert re.search(r"if\s*\(!wired\)", src), (
        "취소 배선 1회 가드(wired)가 사라졌습니다 — build() 재호출 시 리스너 중복(K12)."
    )


def test_picker_header_describes_static_ownership():
    """파일 헤더가 '동적 생성/통합 단계 이관 예정' 낡은 서술 대신 정적 소유를 기술해야 한다(K12)."""
    header = _picker_src().split("(function", 1)[0]
    for stale in ("첫 사용 때 동적으로 만든다", "통합 단계에서 정적 DOM 으로"):
        assert stale not in header, (
            f"pool_picker.js 헤더에 낡은 서술('{stale}')이 남아 있습니다 — 골격은 index.html "
            "정적 소유로 이관됐습니다(K12)."
        )
    assert "index.html" in header and "test_web_dom_contract" in header, (
        "pool_picker.js 헤더가 정적 골격 소유(index.html)와 가드(test_web_dom_contract)를 "
        "기술하지 않습니다(K12)."
    )
