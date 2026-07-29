"""분할된 앱 스타일시트를 한 문자열로 되돌리는 단일 창구.

`web/css/app.css`(1389줄)는 **순서 보존 컷**으로 9조각이 됐다 — 규칙을 옮기지 않고 경계에서만
잘랐으므로 이어붙이면 옛 파일과 **바이트 동일**하다. CSS 는 트리 의미가 없어서 링크 순서대로
이어붙인 문자열이 원본과 등가이고, 그래서 기존 계약 테스트들의 substring·regex 단언은 물론
**전문 카운트**(예: `test_sticky_material` 의 `backdrop-filter:blur(14px)` 2회)와 **주석 텍스트
슬라이스**(`test_interaction_responsiveness` 가 `/* 부유 메뉴`·`/* ---- 공통 컨트롤` 로 자른다)
까지 그대로 참이 된다. 그게 이 방식의 요점이다 — 분할이 게이트를 약화시키지 않는다.

순서를 바꾸면 캐스케이드가 바뀐다. 같은-명시도 hover→상태 쌍(`.navbtn:hover` → `[aria-current]`
류가 최소 13쌍)과 마지막에 와야 하는 `forced-colors` 가 여기 걸려 있다. 그래서 `APP_CSS_FILES`
는 `web/index.html` 의 `<link>` 순서와 같아야 하며, `test_web_css_manifest.py` 가 그 일치와
`web/css/*.css` 전수 등재를 게이트한다(등재 없는 새 파일은 조용히 검사 밖으로 새지 못한다).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_CSS_DIR = ROOT / "web" / "css"

#: 토큰 다음에 실리는 앱 스타일시트 — web/index.html 의 <link> 순서 그대로.
#: 이름이 소유권과 어긋나 보이는 둘은 의도다: `draftcard` 는 「기안」 사망(F6 PR-B) 뒤
#: 작업대(`workbench.js` 가 "wb-preview wc-render f-…" 를 조립)가 실소비자이고, job 은
#: 자란 순서 그대로 `job`/`jobdata`/`tail` 로 갈려 있다. 소유권 재정렬은 시각 회귀 그물을
#: 갖춘 뒤 별건으로 한다 — 지금 이름은 CSS 가 실제로 자란 순서를 말한다.
APP_CSS_FILES = (
    "base.css",           # @font-face·리셋·스크롤바·셸·모션층·.btn/.field·유틸·H-01 타이포
    "draftcard.css",      # table.dmap·.wc-*·.qd-* (작업대가 실소비)
    "editor.css",         # 마법사·table.map·.hchip·.editor-shell
    "job.css",            # 실행 행·거울·결과 3태·runlog·master-detail·.ctx-menu
    "overlay.css",        # #overlayRoot·.modal/.sheet·.pill·.tpllist·데이터 선택·드로어
    "library.css",        # .library-*·.lib-*·.jcard
    "forced-colors.css",  # @media (forced-colors:active) — 앞선 전 구역을 덮는다
    "jobdata.css",        # .jobtb·.fico/.fchip/.fstrip·후보/탐색
    "tail.css",           # .colpanel·.undo-toast·스크롤포트 인벤토리(H-07)·workbench .wb-*
)

#: 셸·갤러리가 싣는 전체 순서(토큰 포함).
ALL_CSS_FILES = ("tokens.css", *APP_CSS_FILES)


def app_css() -> str:
    """앱 스타일시트 조각을 링크 순서대로 이어붙여 돌려준다 — 구 `app.css` 등가."""
    return "".join(
        (WEB_CSS_DIR / name).read_text(encoding="utf-8") for name in APP_CSS_FILES
    )
