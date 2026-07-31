"""코드리뷰 3차(js-shared 클러스터) 회귀 가드 — 공유 이스케이퍼(K1)·pool.js 헤더(K11).

K1: 동일 3줄 HTML 이스케이퍼가 frontend/js 9곳(화면 7 + 피커 2)에 복붙돼 있었다.
``frontend/js/esc.js`` 하나로 통일하고, 사본이 조용히 재유입되거나 로드 순서(공유 파일이
소비 화면보다 먼저)가 깨지는 회귀를 정적으로 차단한다.

N-04 뒤 단일 출처의 **형태**가 둘로 갈렸다: esc.js 는 ``escHtml`` named export 를 내고,
``segview.js`` 는 그것을 직접 import 한다. 아직 IIFE 인 소비자 7개는 중앙 compat 이 되건
``window.escHtml`` 을 계속 읽는다(제거 책임 N-10). 계약 자체는 그대로다 — 정의는 한 곳,
소비자는 전부 배선돼 있고, 공급 지점이 소비자보다 먼저 평가된다. 바뀐 것은 그 공급 지점이
esc.js 자신이 아니라 그것을 끌어오는 compat 이라는 점뿐이다.
txt.js 사본만 ``"`` 를 escape 하지 않는 변종이었는데 ``title="…"``·``value="…"``
속성 컨텍스트에도 쓰이고 있어 따옴표 포함 값이 속성을 깨는 잠복 결함 — 통일이 봉합.

K11: pool.js 헤더 주석이 '기대 DOM…브리지 메서드 추가 예정'이라는 미래형(거짓)
기술이었다 — 실제로는 전부 배선돼 있다. 현재형 기술로 고치고 재퇴행을 가드한다.
"""
from __future__ import annotations

import re

from _web_source import (
    SOURCE_ENTRY,
    SOURCE_JS_DIR,
    evaluated_modules,
    evaluation_site,
    imported_js,
)

WEB_JS = SOURCE_JS_DIR

# 공유 이스케이퍼를 아직 전역으로 읽는 IIFE 소비자들 — 전부 compat 뒤에 평가돼야 한다.
# (draftsession.js·screens/draft.js 는 「기안」 화면과 함께 사망 — F6 PR-B.
#  screens/template.js 는 「템플릿 관리」 화면과 함께 사망 — F8 §10.17.
#  작업대(screens/workbench.js)가 새 소비자로 합류했다.)
ESC_CONSUMERS = (
    "sheet_picker.js", "data_picker.js", "datazone.js",
    "screens/library.js", "screens/editor.js", "screens/job.js",
    "screens/workbench.js",
)

# 이미 ESM 으로 옮겨가 전역 대신 직접 import 하는 소비자(N-04). 순서 계약은 import 그래프가
# 대신 지므로 entry 위치를 묻지 않는다 — 대신 배선 자체를 여기서 단언한다.
ESC_ESM_CONSUMERS = ("segview.js",)


def test_esc_helper_exists_and_escapes_superset():
    """esc.js 가 escHtml 을 named export 로 내고 & < > " 넉 자를 전부 다룬다(txt.js 변종 봉합)."""
    src = (WEB_JS / "esc.js").read_text(encoding="utf-8")
    assert re.search(r"(?m)^export function escHtml\(", src), (
        "esc.js 가 escHtml 을 named export 로 내지 않습니다(K1)."
    )
    assert "window." not in src, (
        "esc.js 가 다시 전역을 만듭니다 — 별칭은 중앙 compat 한 곳만 만듭니다(K1·D-05)."
    )
    for ent in ("&amp;", "&lt;", "&gt;", "&quot;"):
        assert ent in src, f"esc.js 이스케이프 맵에 {ent} 가 없습니다 — 속성 컨텍스트 안전 초집합 회귀(K1)."


def test_esc_provider_evaluated_before_all_consumers():
    """제품 entry 순서 — 이스케이퍼 공급 지점이 모든 소비 IIFE보다 먼저 평가돼야 한다(K1).

    공급 지점은 이제 esc.js 자신이 아니라 그것을 끌어오는 중앙 compat 이다. 이름을 여기
    하드코딩하지 않고 :func:`evaluation_site` 로 옮겨 물으므로, 다음 잎이 이동해도 이 계약은
    같은 질문을 계속 정확히 던진다.
    """
    modules = evaluated_modules(SOURCE_ENTRY.read_text(encoding="utf-8"))
    provider = evaluation_site("esc.js")
    assert provider in modules, f"{provider} 가 제품 entry 에 import되지 않았습니다(K1)."
    assert "esc.js" not in modules, (
        "esc.js 가 entry 에 직접 남아 있습니다 — 잎은 compat 한 경로로만 들어옵니다."
    )
    esc_pos = modules.index(provider)
    for rel in ESC_CONSUMERS:
        assert rel in modules, f"{rel} 이 제품 entry 에 import되지 않았습니다."
        assert modules.index(rel) > esc_pos, (
            f"{rel} 이 {provider} 보다 먼저 평가됩니다 — window.escHtml 미정의 시점 참조(K1)."
        )


def test_no_local_escaper_copies_remain():
    """frontend/js 어디에도 로컬 이스케이퍼 사본이 재유입되지 않아야 한다(K1 9중복 회귀 가드).

    esc.js(단일 출처) 밖에서 `function esc…` 정의나 escape 치환 맵 리터럴이 보이면
    복붙 사본이 되살아난 것 — 전부 공유 헬퍼(전역 별칭 또는 ESM import)를 태워야 한다.
    """
    copy_def = re.compile(r"function\s+esc(Html)?\s*\(")
    escape_map = re.compile(r"""["']&["']\s*:\s*["']&amp;["']""")
    for path in WEB_JS.rglob("*.js"):
        src = path.read_text(encoding="utf-8")
        if path.name == "esc.js":
            continue
        assert not copy_def.search(src), (
            f"{path.name} 에 로컬 이스케이퍼 정의가 재유입됐습니다 — window.escHtml 을 쓰세요(K1)."
        )
        assert not escape_map.search(src), (
            f"{path.name} 에 escape 치환 맵 사본이 재유입됐습니다 — window.escHtml 을 쓰세요(K1)."
        )
    # 소비 파일들은 실제로 공유 헬퍼를 참조해야 한다(정의 삭제만 하고 미배선 방지).
    for rel in ESC_CONSUMERS:
        src = (WEB_JS / rel).read_text(encoding="utf-8")
        assert "window.escHtml" in src, f"{rel} 이 window.escHtml 을 참조하지 않습니다(K1)."
    for rel in ESC_ESM_CONSUMERS:
        src = (WEB_JS / rel).read_text(encoding="utf-8")
        assert re.search(r'(?m)^import \{ escHtml \} from "\./esc\.js";', src), (
            f"{rel} 이 escHtml 을 ESM import 하지 않습니다 — 배선이 끊겼습니다(K1)."
        )


def test_data_picker_header_describes_delivered_state():
    """data_picker.js 헤더가 배달된 현재 상태를 기술해야 한다 — 미래형 거짓 기술 가드(K11).

    구 pool.js 헤더 계약의 승계분(재작성 F1): 헤더가 말하는 소유 경계와 배선이 실제 코드에
    있어야 한다(주석-코드 정합).
    """
    src = (WEB_JS / "data_picker.js").read_text(encoding="utf-8")
    header = src.split("(function", 1)[0]  # IIFE 이전 = 파일 헤더 주석
    for stale in ("추가 예정", "그때까지", "임시로"):
        assert stale not in header, (
            f"data_picker.js 헤더에 낡은 미래형 기술('{stale}')이 남아 있습니다(K11)."
        )
    body = src.split("(function", 1)[1]
    assert "PoolController" in header and "load_pool" in header, (
        "data_picker.js 헤더가 소유 경계(pool 컨트롤러 소비·호스트 마운트)를 기술하지 않습니다(K11)."
    )
    assert "pickPoolDataFile" in body and "poolRegBrowse" in body, (
        "헤더가 기술한 등록 모달 배선(poolRegBrowse→pickPoolDataFile)이 코드에 없습니다."
    )
