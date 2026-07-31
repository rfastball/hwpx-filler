"""프런트엔드 **정적 소스 역할**을 읽는 단일 테스트 창구.

N-03 M1부터 canonical source는 ``frontend/``이고 제품 entry는 ``frontend/src/main.js``다.
이 모듈은 그 물리 경로를 정적 DOM/JS/CSS 계약에서 떼어 내어, 테스트가 저장소 루트에서
``frontend/``이나 폐기된 ``web/``을 직접 조립하지 않게 한다. 런타임·selftest·실렌더·
패키징 산출물 resolver가 아니며, 그 역할들은 sealed ``build/web/`` 소비자로 별도 전환한다.

분할된 앱 CSS는 순서 보존 컷이다. entry의 side-effect import 순서는 정확히
``tokens, base, draftcard, editor, job, overlay, library, forced-colors, jobdata, tail``이다.
``forced-colors`` 뒤에도 ``jobdata``와 ``tail``이 오므로, 그 두 조각을 앞으로 당기는 과거
설명으로 재정렬하면 안 된다. :data:`ALL_CSS_FILES`가 이 실제 캐스케이드 순서의 매니페스트고,
``test_web_css_manifest.py``가 product entry의 import 순서와 디스크 전수를 함께 게이트한다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: canonical frontend source와 단일 제품 module entry.
SOURCE_ROOT = REPO_ROOT / "frontend"
SOURCE_INDEX = SOURCE_ROOT / "index.html"
SOURCE_ENTRY = SOURCE_ROOT / "src" / "main.js"
SOURCE_COMPAT = SOURCE_ROOT / "src" / "compat.js"
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

#: N-04에서 true ESM named export로 바뀐 잎 모듈 — 제품 entry가 **직접 import하지 않는다**.
#: 넷은 중앙 :data:`COMPAT_MODULE` 하나를 통해서만 제품 그래프에 닿고, 기존 전역 별칭
#: (``Copy``·``escHtml``·``Guard``·``SegView``)도 거기서만 만들어진다. 파일마다 별칭을
#: 되살리면 생산자가 다시 흩어져 D-05의 "수량 단조 감소" 계측점이 사라진다.
LEAF_ESM_FILES = (
    "copy.js",
    "esc.js",
    "guard.js",
    "segview.js",
)

#: N-05에서 true ESM으로 바뀐 공용 UI 서비스 15개. 잎과 같은 규칙을 따른다 — entry가 직접
#: 싣지 않고 중앙 compat이 끌어오며, 임시 전역 별칭도 거기서만 만들어진다. 순서는 N-04까지
#: entry가 싣던 실행 순서 그대로다(계약이 아니라 **기록**이다: 이제 평가 순서는 compat의
#: import 그래프가 정한다).
SERVICE_ESM_FILES = (
    "theme.js",
    "personalization.js",
    "preserve.js",
    "modal.js",
    "surface_sheet.js",
    "undo_toast.js",
    "sheet_picker.js",
    "data_picker.js",
    "pathtrack.js",
    "relink.js",
    "popover.js",
    "datazone.js",
    "intent.js",
    "grouplist.js",
    "editor_entry.js",
)

#: N-06에서 named factory(true ESM)로 바뀐 화면 넷과 앱 셸. entry가 직접 싣지 않고 중앙
#: compat이 import해 **정확히 한 번** 구성하며, 구성 순서는 구 entry의 IIFE 평가 순서
#: 그대로다(화면 넷 → 앱 셸). 화면 간 간선과 화면→Nav 간선은 import가 아니라 compat의
#: late-bound 콜백 테이블이 진다 — 그래서 import 그래프에 editor↔job 순환이 없다.
SCREEN_ESM_FILES = (
    "screens/library.js",
    "screens/editor.js",
    "screens/job.js",
    "screens/workbench.js",
    "app.js",
)

#: compat을 통해 제품 그래프에 닿는 ESM 모듈 전체(잎 4 + 서비스 15 + 화면·셸 5).
ESM_FILES = (*LEAF_ESM_FILES, *SERVICE_ESM_FILES, *SCREEN_ESM_FILES)

#: ESM 모듈의 임시 전역 별칭을 만드는 유일한 자리(제품 entry 기준 ``./compat.js``).
COMPAT_MODULE = "compat.js"

#: 아직 ESM이 아니라 entry가 side-effect import하는 IIFE — ``bridge.js`` 하나(N-07 소유).
LEGACY_JS_FILES = ("bridge.js",)

#: compat이 들어가는 자리 — ``bridge.js`` 바로 뒤. compat은 평가 시점에 ``window.Bridge``를
#: 객체째 캡처하므로 bridge가 반드시 먼저 평가돼야 한다. 화면·서비스는 compat의 import
#: 그래프로만 들어오고, 별칭 25개는 compat 본문 말미(모든 구성 뒤)에 선다.
COMPAT_ENTRY_POSITION = 1


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
    """gallery 등 비제품 문서의 ``<link rel="stylesheet">`` 순서를 읽는다."""
    return tuple(
        re.findall(
            rf'<link\s+rel="stylesheet"\s+href="{re.escape(prefix)}([^"]+)"',
            html,
        )
    )


def side_effect_imports(entry: str) -> tuple[str, ...]:
    """제품 entry의 정적 side-effect import 경로를 문서 순서대로 읽는다."""
    return tuple(
        re.findall(
            r'^\s*import\s+["\']([^"\']+)["\'];\s*$',
            entry,
            flags=re.M,
        )
    )


def imported_css(entry: str) -> tuple[str, ...]:
    """제품 entry가 싣는 CSS 파일명을 import 순서대로 읽는다."""
    prefix = "../css/"
    return tuple(
        path.removeprefix(prefix)
        for path in side_effect_imports(entry)
        if path.startswith(prefix)
    )


def imported_js(entry: str) -> tuple[str, ...]:
    """제품 entry가 싣는 legacy IIFE 파일명을 import 순서대로 읽는다."""
    prefix = "../js/"
    return tuple(
        path.removeprefix(prefix)
        for path in side_effect_imports(entry)
        if path.startswith(prefix)
    )


def entry_js_manifest() -> tuple[str, ...]:
    """제품 entry가 실을 JS side-effect import 경로를 실행 순서대로 조립한다."""
    legacy = [f"../js/{name}" for name in LEGACY_JS_FILES]
    return (
        *legacy[:COMPAT_ENTRY_POSITION],
        f"./{COMPAT_MODULE}",
        *legacy[COMPAT_ENTRY_POSITION:],
    )


def evaluated_modules(entry: str) -> tuple[str, ...]:
    """제품 entry의 JS import를 **평가 순서의 모듈 이름**으로 정규화한다.

    ``../js/X``는 ``X``로, 중앙 호환 계층은 ``compat.js``로 읽는다. CSS import는 뺀다.
    """
    names: list[str] = []
    for path in side_effect_imports(entry):
        if path.startswith("../js/"):
            names.append(path.removeprefix("../js/"))
        elif path == f"./{COMPAT_MODULE}":
            names.append(COMPAT_MODULE)
    return tuple(names)


def module_imports(source: str) -> tuple[str, ...]:
    """모듈이 정적으로 끌어오는 **모든** import 경로를 문서 순서대로 읽는다.

    :func:`side_effect_imports`는 ``import "x";`` 형태만 센다. ESM 전환이 진행되면서 모듈은
    ``import { X } from "x";``로 옮겨가는데, 그 둘을 같은 눈으로 보지 않으면 "entry 목록에서
    사라졌다"는 사실을 아무도 말하지 않는 창이 생긴다 — ``in`` 단언만 깨지고 ``not in``
    단언은 애초에 없기 때문이다. 도달성을 묻는 계약은 이 함수로 물어야 한다.
    """
    return tuple(
        re.findall(
            r'(?m)^\s*import\s+(?:[^"\';]*?\s+from\s+)?["\']([^"\']+)["\'];',
            source,
        )
    )


def compat_imports() -> tuple[str, ...]:
    """중앙 compat이 끌어오는 ``../js/`` 모듈 이름을 import 순서대로 읽는다."""
    prefix = "../js/"
    return tuple(
        path.removeprefix(prefix)
        for path in module_imports(SOURCE_COMPAT.read_text(encoding="utf-8"))
        if path.startswith(prefix)
    )


def reaches_product_graph(name: str) -> bool:
    """모듈이 제품 그래프에 **실제로 닿는지** 묻는다 — entry 직접이든 compat 경유든.

    "이 파일이 앱에 실리는가"를 ``imported_js(entry)`` 로 묻던 계약들의 후계다. 그 질문은
    파일이 entry의 bare import 목록에 있는지를 봤는데, ESM으로 옮겨간 모듈은 그 목록에서
    사라지므로 같은 문자열 검사로는 "안 실린다"와 "이름이 옮겨졌다"를 구별하지 못한다.
    """
    if name in ESM_FILES:
        return name in compat_imports() and COMPAT_MODULE in evaluated_modules(
            SOURCE_ENTRY.read_text(encoding="utf-8")
        )
    return name in imported_js(SOURCE_ENTRY.read_text(encoding="utf-8"))


def evaluation_site(name: str) -> str:
    """모듈 이름을 **제품 entry에서 실제로 평가되는 지점**의 이름으로 옮긴다.

    "공유 헬퍼가 소비 화면보다 먼저 실행되는가"를 묻던 계약들은 모듈 파일 이름을 entry
    순서에서 찾았다. N-04의 잎 넷과 N-05의 서비스 열다섯은 entry가 직접 싣지 않고 중앙
    compat이 끌어오므로, 같은 질문의 답은 그 파일이 아니라 compat의 자리에 있다. 이 함수가
    그 옮김을 한 곳에 둔다 — 각 테스트가 따로 ``compat.js``를 하드코딩하면 다음 모듈이
    옮겨갈 때 조용히 낡는다.
    """
    return COMPAT_MODULE if name in ESM_FILES else name
