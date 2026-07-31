"""코드리뷰 3차(js-shared 클러스터) 회귀 가드 — 공유 이스케이퍼(K1)·pool.js 헤더(K11).

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
    SOURCE_ENTRY,
    SOURCE_JS_DIR,
    evaluated_modules,
    evaluation_site,
    imported_js,
)

WEB_JS = SOURCE_JS_DIR

# 전역 대신 직접 import 하는 소비자 전수(N-04 잎 + N-05 서비스 + N-06 화면 넷). 순서 계약은
# import 그래프가 대신 지므로 entry 위치를 묻지 않는다 — 대신 배선 자체를 여기서 단언한다.
# 질문은 K1 그대로다: **공유 헬퍼를 실제로 태우는가**. 이 목록을 지우면 그 질문 자체가
# 사라지므로, 소비자가 ESM 으로 옮겨갈 때 여기 옮겨 적는 것이 계약이다. N-06 으로 전역
# 소비자(구 ESC_CONSUMERS 화면 넷)가 0 이 되어 목록이 하나로 합쳐졌다 — draftsession.js·
# screens/draft.js 는 「기안」 화면과 함께(F6 PR-B), screens/template.js 는 「템플릿 관리」
# 화면과 함께(F8 §10.17) 사망.
ESC_ESM_CONSUMERS = (
    "segview.js",
    "sheet_picker.js", "data_picker.js", "datazone.js",
    "grouplist.js", "pathtrack.js",
    "screens/library.js", "screens/editor.js", "screens/job.js",
    "screens/workbench.js",
)


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
    """이스케이퍼 공급이 제품 그래프에 닿고, 소비 순서는 import 간선이 진다(K1 후계).

    구 형태는 공급 지점과 소비 IIFE 의 entry 위치를 비교했다. N-06 으로 소비자 전원이
    ESM import 로 옮겨가 entry 에 소비자가 없으므로, 순서는 언어 규칙(import 가 본문보다
    먼저 평가)이 담보하고 여기 남는 질문은 공급 자체다 — compat 경유로 그래프에 닿는가,
    그리고 두 경로로 들어와 순서 추론을 무의미하게 만들지 않는가.
    """
    modules = evaluated_modules(SOURCE_ENTRY.read_text(encoding="utf-8"))
    provider = evaluation_site("esc.js")
    assert provider in modules, f"{provider} 가 제품 entry 에 import되지 않았습니다(K1)."
    assert "esc.js" not in modules, (
        "esc.js 가 entry 에 직접 남아 있습니다 — 잎은 compat 한 경로로만 들어옵니다."
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
    src = (WEB_JS / "data_picker.js").read_text(encoding="utf-8")
    header, body = src.split("import ", 1)  # 첫 import 이전 = 파일 헤더 주석
    for stale in ("추가 예정", "그때까지", "임시로"):
        assert stale not in header, (
            f"data_picker.js 헤더에 낡은 미래형 기술('{stale}')이 남아 있습니다(K11)."
        )
    assert "PoolController" in header and "load_pool" in header, (
        "data_picker.js 헤더가 소유 경계(pool 컨트롤러 소비·호스트 마운트)를 기술하지 않습니다(K11)."
    )
    assert "pickPoolDataFile" in body and "poolRegBrowse" in body, (
        "헤더가 기술한 등록 모달 배선(poolRegBrowse→pickPoolDataFile)이 코드에 없습니다."
    )
