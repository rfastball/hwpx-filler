"""프런트엔드 **정적 소스 역할**을 읽는 단일 테스트 창구.

N-02 P0에서는 제품 런타임과 canonical source가 아직 모두 ``web/``에 있다. 이 모듈은 그
물리 경로를 정적 DOM/JS/CSS 계약에서 떼어 내어, 테스트가 저장소 루트에서 ``web/``을 직접
조립하지 않게 한다. 런타임·selftest·실렌더·패키징 산출물 resolver가 아니며, 그 역할들은
중앙 M1 컷오버에서 sealed ``build/web/`` 소비자로 별도 전환한다.

분할된 앱 CSS는 순서 보존 컷이다. 링크 순서는 정확히
``tokens, base, draftcard, editor, job, overlay, library, forced-colors, jobdata, tail``이다.
``forced-colors`` 뒤에도 ``jobdata``와 ``tail``이 오므로, 그 두 조각을 앞으로 당기는 과거
설명으로 재정렬하면 안 된다. :data:`ALL_CSS_FILES`가 이 실제 캐스케이드 순서의 매니페스트고,
``test_web_css_manifest.py``가 소스 index의 링크 순서와 디스크 전수를 함께 게이트한다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 현재 canonical frontend source. N-03 중앙 활성화 전까지 물리 루트는 ``web/`` 그대로다.
SOURCE_ROOT = REPO_ROOT / "web"
SOURCE_INDEX = SOURCE_ROOT / "index.html"
SOURCE_CSS_DIR = SOURCE_ROOT / "css"
SOURCE_JS_DIR = SOURCE_ROOT / "js"

#: 토큰 다음에 실리는 앱 스타일시트 — source index의 실제 ``<link>`` 순서 그대로.
#: 이름이 소유권과 어긋나 보이는 둘은 의도다: ``draftcard``는 「기안」 사망(F6 PR-B) 뒤
#: 작업대(``workbench.js``가 ``wb-preview wc-render f-…``를 조립)가 실소비자이고, job은
#: 자란 순서 그대로 ``job``/``jobdata``/``tail``로 갈려 있다. 소유권 재정렬은 시각 회귀
#: 그물을 갖춘 뒤 별건으로 한다 — 지금 이름은 CSS가 실제로 자란 순서를 말한다.
APP_CSS_FILES = (
    "base.css",           # @font-face·리셋·스크롤바·셸·모션층·.btn/.field·유틸·H-01 타이포
    "draftcard.css",      # table.dmap·.wc-*·.qd-* (작업대가 실소비)
    "editor.css",         # 마법사·table.map·.hchip·.editor-shell
    "job.css",            # 실행 행·거울·결과 3태·runlog·master-detail·.ctx-menu
    "overlay.css",        # #overlayRoot·.modal/.sheet·.pill·.tpllist·데이터 선택·드로어
    "library.css",        # .library-*·.lib-*·.jcard
    "forced-colors.css",  # @media (forced-colors:active) — 현재 위치 뒤에도 두 조각이 더 온다
    "jobdata.css",        # .jobtb·.fico/.fchip/.fstrip·후보/탐색
    "tail.css",           # .colpanel·.undo-toast·스크롤포트 인벤토리(H-07)·workbench .wb-*
)

#: 정적 소스 셸이 싣는 전체 CSS 순서(토큰 포함).
ALL_CSS_FILES = ("tokens.css", *APP_CSS_FILES)


def source_path(*parts: str) -> Path:
    """정적 프런트엔드 소스 루트 아래 경로를 돌려준다."""
    return SOURCE_ROOT.joinpath(*parts)


def source_text(*parts: str) -> str:
    """정적 프런트엔드 소스 파일을 UTF-8로 읽는다."""
    return source_path(*parts).read_text(encoding="utf-8")


def app_css() -> str:
    """앱 CSS 조각을 실제 링크 순서대로 이어붙여 돌려준다 — 구 ``app.css`` 등가."""
    return "".join(
        (SOURCE_CSS_DIR / name).read_text(encoding="utf-8")
        for name in APP_CSS_FILES
    )


def strip_comments(css: str) -> str:
    """``/* … */``를 걷어 **규칙만** 남긴다.

    CSS 주석은 결정 근거와 죽은 선택자 이름을 일부러 보존한다. 그 산문을 규칙으로 세면
    “없어야 하는 선택자가 있다”는 거짓 실패가 난다. 구간 컷이 주석 텍스트를 경계로 쓰는
    경우에는 **자른 뒤에** 이 함수를 호출한다.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def linked_css(html: str, prefix: str) -> tuple[str, ...]:
    """``<link rel="stylesheet">``의 CSS 파일명을 문서 순서대로 뽑는다."""
    return tuple(
        re.findall(
            rf'<link\s+rel="stylesheet"\s+href="{re.escape(prefix)}([^"]+)"',
            html,
        )
    )
