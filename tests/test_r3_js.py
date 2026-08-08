"""코드리뷰 3차(js-shared 클러스터) 회귀 가드 — 공유 이스케이퍼(K1)·pool.js 헤더(K11).

R5-99 감사 B2 개정: `esc.js` 자체가 소비자 0 실측으로 삭제됐다 — 이스케이프 소유는
React 의 text/attribute 경계다. K1 이 막던 결함(복붙 사본 9중복)은 이제 「사본·헬퍼
재유입 금지」 음성 가드가 진다 — 주체가 죽어도 결함류를 막는 질문은 살아 있다.

K1: 동일 3줄 HTML 이스케이퍼가 frontend/js 9곳(화면 7 + 피커 2)에 복붙돼 있었다.
``frontend/js/esc.js`` 하나로 통일하고, 사본이 조용히 재유입되거나 로드 순서(공유 파일이
소비 화면보다 먼저)가 깨지는 회귀를 정적으로 차단한다.

N-06 뒤 소비자 전원이 ``escHtml`` named export 를 직접 import 한다 — ``window.escHtml``
판독은 제품 코드에 0 이고, 전역 별칭은 Python selftest 프로브를 위해 중앙 compat 이
유지한다(제거 책임 N-10). 계약 자체는 K1 그대로다 — 정의는 한 곳, 소비자는 전부 배선돼
있고, 공급이 소비보다 먼저 평가된다(이제 import 언어 규칙이 담보).
txt.js 사본만 ``"`` 를 escape 하지 않는 변종이었는데 ``title="…"``·``value="…"``
속성 컨텍스트에도 쓰이고 있어 따옴표 포함 값이 속성을 깨는 잠복 결함 — 통일이 봉합.

K11: pool.js 헤더 주석이 '기대 DOM…브리지 메서드 추가 예정'이라는 미래형(거짓)
기술이었다 — 실제로는 전부 배선돼 있다. 현재형 기술로 고치고 재퇴행을 가드한다.
"""
from __future__ import annotations

import re

from _web_source import (
    SOURCE_JS_DIR,
    bootstrap_imports,
)

WEB_JS = SOURCE_JS_DIR

# 전역 대신 직접 import 하는 소비자 전수(N-04 잎 + N-05 서비스 + N-06 화면 넷). 순서 계약은
# import 그래프가 대신 지므로 entry 위치를 묻지 않는다 — 대신 배선 자체를 여기서 단언한다.
# 질문은 K1 그대로다: **공유 헬퍼를 실제로 태우는가**. 이 목록을 지우면 그 질문 자체가
# 사라지므로, 소비자가 ESM 으로 옮겨갈 때 여기 옮겨 적는 것이 계약이다. N-06 으로 전역
# 소비자(구 ESC_CONSUMERS 화면 넷)가 0 이 되어 목록이 하나로 합쳐졌다 — draftsession.js·
# screens/draft.js 는 「기안」 화면과 함께(F6 PR-B), screens/template.js 는 「템플릿 관리」
# 화면과 함께(F8 §10.17) 사망.
#: 아직 문자열을 조립하는 legacy 소비자 — 그 안에 사용자·파일 유래 값을 끼우면 이 잎을 탄다.
#:
#: R4-02 가 다섯을 걷었다(`segview.js`·`sheet_picker.js`·`screens/editor.js`·
#: `screens/workbench.js` 삭제, `grouplist.js` 는 `createMoveDialog` 절제로 값 끼움이 0).
#: React 후계는 이 목록에 **들어오지 않는다** — 요소 트리라 이스케이프의 소유자가 React 이고,
#: 문자열이 남은 한 자리(편집기 행 메뉴)는 `dataset`·`textContent` 로 지어 규칙 자체를 안 든다.
#: 그 자리의 계약은 `tests/js/r4_editor.test.js` 가 실행으로 잰다.
#: R4-04가 마지막 문자열 조립 소비자 pathtrack.js를 PathActions 요소 트리로 옮겼다.
#: 사용자·파일 유래 값은 이제 전부 React text/attribute 경계가 escape한다.
ESC_ESM_CONSUMERS: tuple[str, ...] = ()


def test_esc_helper_retired_without_revival():
    """esc.js 는 R5-99 B2 로 퇴장했다 — 파일도 import 도 되살아나지 않는다.

    구 K1 계약(공급 존재·순서)은 소비자가 0 이 되며 질문 자체가 소멸했다. 남는 것은
    「되살아나지 않는다」다 — RETIRED_R5_MODULES 가 경로를, 이 테스트가 그래프를 봉한다.
    """
    assert not (WEB_JS / "esc.js").exists(), (
        "esc.js 가 되살아났습니다 — 이스케이프 소유는 React 입니다(R5-99 B2)."
    )
    # entry 는 ../js/* 를 직접 싣지 않으므로 entry 목록 검사는 공허하다(L16 반증) —
    # 재유입의 실통로인 합성 루트 import 그래프를 직접 본다.
    assert "esc.js" not in bootstrap_imports(), (
        "합성 루트가 삭제된 esc.js 를 다시 끌어옵니다."
    )


def test_no_local_escaper_copies_remain():
    """frontend/js 어디에도 로컬 이스케이퍼 사본이 재유입되지 않아야 한다(K1 9중복 회귀 가드).

    esc.js(단일 출처) 밖에서 `function esc…` 정의나 escape 치환 맵 리터럴이 보이면
    복붙 사본이 되살아난 것 — 전부 공유 헬퍼(전역 별칭 또는 ESM import)를 태워야 한다.
    """
    copy_def = re.compile(r"function\s+esc(Html)?\s*\(")
    escape_map = re.compile(r"""["']&["']\s*:\s*["']&amp;["']""")
    paths = [*WEB_JS.rglob("*.js"), *(WEB_JS.parent / "src").rglob("*.ts")]
    for path in paths:
        src = path.read_text(encoding="utf-8")
        assert not copy_def.search(src), (
            f"{path.name} 에 로컬 이스케이퍼 정의가 재유입됐습니다 — window.escHtml 을 쓰세요(K1)."
        )
        assert not escape_map.search(src), (
            f"{path.name} 에 escape 치환 맵 사본이 재유입됐습니다 — window.escHtml 을 쓰세요(K1)."
        )
    # 소비 파일들은 실제로 공유 헬퍼를 참조해야 한다(정의 삭제만 하고 미배선 방지).
    # 상대 경로는 소비자의 위치가 정한다 — screens/ 아래는 한 단계 올라온다.
    for rel in ESC_ESM_CONSUMERS:
        src = (WEB_JS / rel).read_text(encoding="utf-8")
        prefix = r"\.\./" if rel.startswith("screens/") else r"\./"
        assert re.search(rf'(?m)^import \{{ escHtml \}} from "{prefix}esc\.js";', src), (
            f"{rel} 이 escHtml 을 ESM import 하지 않습니다 — 배선이 끊겼습니다(K1)."
        )


def test_data_picker_header_describes_delivered_state():
    """data_picker.js 헤더가 배달된 현재 상태를 기술해야 한다 — 미래형 거짓 기술 가드(K11).

    구 pool.js 헤더 계약의 승계분(재작성 F1): 헤더가 말하는 소유 경계와 배선이 실제 코드에
    있어야 한다(주석-코드 정합).
    """
    src = (WEB_JS.parent / "src" / "screens" / "data_picker.ts").read_text(encoding="utf-8")
    header, body = src.split("import ", 1)  # 첫 import 이전 = 파일 헤더 주석
    for stale in ("추가 예정", "그때까지", "임시로"):
        assert stale not in header, (
            f"data_picker.js 헤더에 낡은 미래형 기술('{stale}')이 남아 있습니다(K11)."
        )
    assert "React 표면" in header and "session/loading/status" in header, (
        "data_picker.ts 헤더가 controller·React producer 소유 경계를 기술하지 않습니다(K11)."
    )
    assert 'invoke("pick_data_file"' in body and "poolRegBrowse" in body, (
        "헤더가 기술한 파일 선택·등록 모달 배선이 코드에 없습니다."
    )
