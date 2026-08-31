"""프런트엔드 **정적 소스 역할**을 읽는 단일 테스트 창구.

N-03 M1부터 canonical source는 ``frontend/``이고 제품 entry는 ``frontend/src/main.js``다.
이 모듈은 그 물리 경로를 정적 DOM/JS/CSS 계약에서 떼어 내어, 테스트가 저장소 루트에서
``frontend/``이나 폐기된 ``web/``을 직접 조립하지 않게 한다. 런타임·selftest·실렌더·
패키징 산출물 resolver가 아니며, 그 역할들은 sealed ``build/web/`` 소비자로 별도 전환한다.

분할된 앱 CSS는 순서 보존 컷이다. entry의 side-effect import 순서는 정확히
``tokens, base, draftcard, editor, job, overlay, library, forced-colors, jobdata, tail``이다.
``forced-colors`` 뒤에도 ``jobdata``와 ``tail``이 오므로, 그 두 조각을 앞으로 당기는 과거
설명으로 재정렬하면 안 된다. :data:`ALL_CSS_FILES`가 이 실제 캐스케이드 순서의 공유
매니페스트다.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ContractError(ValueError):
    """영속 architecture 계약을 exact하게 해석할 수 없을 때의 fail-closed 오류."""

#: canonical frontend source와 단일 제품 module entry.
SOURCE_ROOT = REPO_ROOT / "frontend"
SOURCE_INDEX = SOURCE_ROOT / "index.html"
SOURCE_ENTRY = SOURCE_ROOT / "src" / "main.js"
SOURCE_BOOTSTRAP = SOURCE_ROOT / "src" / "bootstrap.js"
SOURCE_CSS_DIR = SOURCE_ROOT / "css"
SOURCE_JS_DIR = SOURCE_ROOT / "js"

#: 최종 제품 셸의 장기 화면 집합. 정적 source와 실 WebView2가 같은 값을 소비한다.
NAV_SCREENS = ("library", "job")

#: 토큰 다음에 실리는 앱 스타일시트 — source index의 실제 ``<link>`` 순서 그대로.
#: 이름이 소유권과 어긋나 보이는 둘은 의도다: ``draftcard``는 「기안」 사망(F6 PR-B) 뒤
#: 작업대(``workbench.js``가 ``wb-preview wc-render f-…``를 조립)가 실소비자이고, job은
#: 자란 순서 그대로 ``job``/``jobdata``/``tail``로 갈려 있다. 소유권 재정렬은 시각 회귀
#: 그물을 갖춘 뒤 별건으로 한다 — 지금 이름은 CSS가 실제로 자란 순서를 말한다.
APP_CSS_FILES = (
    "base.css",           # @font-face·리셋·스크롤바·셸·모션층·.btn/.field·유틸·H-01 타이포
    "draftcard.css",      # table.dmap·.wc-*·.qd-* (작업대가 실소비)
    "editor.css",         # 마법사·table.map·.hchip·.editor-shell
    "job.css",            # 실행 행·거울·결과 3태·master-detail·.ctx-menu
    "overlay.css",        # #overlayRoot·.modal/.sheet·.pill·.tpllist·데이터 선택·드로어
    "library.css",        # .library-*·.lib-*·.jcard
    "forced-colors.css",  # @media (forced-colors:active) — 현재 위치 뒤에도 두 조각이 더 온다
    "jobdata.css",        # .jobtb·.fico/.fchip/.fstrip·후보/탐색
    "tail.css",           # .colpanel·.undo-toast·스크롤포트 인벤토리(H-07)·workbench .wb-*
)

#: 정적 소스 셸이 싣는 전체 CSS 순서(토큰 포함).
ALL_CSS_FILES = ("tokens.css", *APP_CSS_FILES)

#: N-04에서 true ESM named export로 바뀐 잎 모듈 — 제품 entry가 **직접 import하지 않는다**.
#: 넷은 :data:`BOOTSTRAP_MODULE` 하나를 통해서만 제품 그래프에 닿는다. N-10 이전에는 그
#: 자리가 임시 전역 별칭(``Copy``·``escHtml``·``Guard``·``SegView``)의 단일 생산자이기도
#: 했으나, 별칭 스물일곱은 N-10에서 0이 됐고 남은 것은 합성 책임뿐이다.
#: R5-99 감사 B2 — copy.js·esc.js 는 소비자 0 실측으로 삭제됐다(카피 단일 출처는 소비처가
#: index.html 하나로 줄어 HTML 자체가 단일 출처, 이스케이프 소유는 React text/attribute 경계).
LEAF_ESM_FILES = (
    "guard.js",
)

#: N-05에서 true ESM으로 바뀐 공용 UI 서비스 가운데 R5-01 뒤에도 ``frontend/js``에 남은 5개.
#: Data picker·DataZone·Relink는 ``frontend/src/screens/*.ts`` React producer/controller로 승계돼
#: 이 legacy-JS 매니페스트에서는 빠진다. 잎과 같은 규칙을 따른다 — entry가 직접
#: 싣지 않고 합성 루트가 끌어온다. 순서는 N-04까지 entry가 싣던 실행 순서 그대로다(계약이
#: 아니라 **기록**이다: 이제 평가 순서는 합성 루트의 import 그래프가 정한다).
#: preserve.js 는 R5-99 B2 에서 selftest 소유(src/selftest/preserve.js)로 이동 — 제품
#: 소비자 0(React 는 서브트리 재구성이 없어 되찾을 포커스·캐럿이 생기지 않는다).
SERVICE_ESM_FILES = (
    "surface_sheet.js",
    "undo_toast.js",
    "popover.js",
    "intent.js",
)

#: R5-01 뒤 legacy JS 화면·셸 모듈은 0개다. 앱 셸은 ``frontend/src/shell/app.ts``로
#: 승계됐고 화면 간 간선과 화면→Nav 간선은 late-bound 콜백 테이블이 진다.
SCREEN_ESM_FILES: tuple[str, ...] = ()

#: 「문서 만들기」 실행·결과 표면의 React 후계 셋. legacy ``screens/job.js`` 하나를 읽던
#: 정적 계약들이 겨눌 자리다 — 한 파일이 셋으로 갈렸으므로 **읽는 자리도 한 곳에 둔다**
#: (각 테스트가 세 경로를 손으로 열거하면 넷째가 생길 때 조용히 낡는다).
REACT_JOB_RUN_FILES = (
    "src/screens/job_run.ts",
    "src/screens/job_result.ts",
    "src/screens/job_preview.ts",
    "src/screens/job_run_state.ts",
    "src/screens/job_relink.ts",
)

#: 합성 루트를 통해 제품 그래프에 닿는 legacy-JS ESM 모듈 전체.
#: N-07에서 마지막 IIFE를 벗고 named factory(true ESM)가 된 브리지. 자리는 특별하다: 합성
#: 루트가 이것을 **정확히 한 번** 구성해 산물을 화면·서비스에 객체째 넘긴다. 구 IIFE가
#: 스스로 만들던 ``Bridge``·``__push`` 두 전역은 N-07에서 합성 루트로 옮겨왔다가 N-10에서
#: 나머지 스물다섯과 함께 사라졌다.
BRIDGE_ESM_FILES = ("bridge.js",)

ESM_FILES = (*LEAF_ESM_FILES, *SERVICE_ESM_FILES, *SCREEN_ESM_FILES, *BRIDGE_ESM_FILES)

#: 제품 합성 루트(제품 entry 기준 ``./bootstrap.js``). N-10 이전 이름은 ``compat.js``였다 —
#: 그 파일은 합성과 **임시 전역 별칭 스물일곱의 단일 생산자**를 겸했고(D-05), 별칭이 0이
#: 되면서 이름도 함께 은퇴했다. 별칭 줄만 지우고 ``compat``이라는 이름을 남기면 "호환 계층이
#: 아직 있다"는 거짓 표식이 남는다.
BOOTSTRAP_MODULE = "bootstrap.js"

#: 합성 루트가 내보내는 유일한 이름 — 제품 entry가 **정확히 한 번** 부른다.
BOOTSTRAP_EXPORT = "bootProduct"

#: 제품 파사드 모듈 — 합성 루트와 같은 ``frontend/src/``에 산다(``../js/``가 아니다).
PRODUCT_API_MODULE = "product_api.js"

#: 제품 최종 공개 API 이름. 임시 별칭과 **다른 계정**이었고(D-06) 별칭이 전부 사라진
#: N-10 뒤에도 남는다. 정상 실행에서 제품 코드가 만드는 전역은 이 하나뿐이다.
PRODUCT_API_GLOBAL = "__hwpx"

#: selftest 공개 API 이름(D-07). 생산자는 ``frontend/src/selftest/api.js`` 하나이고
#: 호스트 capability가 있을 때만 선다 — 정상 실행에는 own property로 존재하지 않는다.
SELFTEST_API_GLOBAL = "__hwpxTest"

#: 제품 코드가 만들어도 되는 전역의 **전수**. 플랫폼이 주입하는 ``pywebview``는 제품이
#: 만드는 것이 아니라 여기 없다. 이 집합을 넓히는 것은 #372 상향 사유다.
ALLOWED_PRODUCT_GLOBALS = frozenset({PRODUCT_API_GLOBAL, SELFTEST_API_GLOBAL})

#: N-10이 지운 임시 전역 별칭 스물일곱 — 생산자도 소비자도 0이어야 한다. 목록을 남기는
#: 이유는 **되살아나는 모양을 이름으로 겨누기** 위해서다. 수량만 세면 다른 이름이 새로
#: 생겨도 초록이고, 이름만 세면 수량 회귀를 놓친다.
RETIRED_COMPAT_GLOBALS = (
    "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent",
    "UndoToast", "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization",
    "SheetPicker", "PathTrack", "Relink", "DataZone", "DataPicker", "EditorEntry",
    "LibraryScreen", "EditorScreen", "JobScreen", "WorkbenchScreen", "Nav",
    "AppCloseGuard", "Bridge", "__push",
)

#: entry가 side-effect import하는 IIFE — N-07에서 **0개**가 됐다. ``bridge.js``가 ESM factory로
#: 바뀌며 합성 루트의 static import로 그래프에 들어왔고, 그와 함께 "먼저 평가돼야 한다"는
#: 순서 계약을 entry에 걸던 마지막 자리도 사라졌다.
LEGACY_JS_FILES: tuple[str, ...] = ()

#: 합성 루트가 들어가는 자리 — entry의 JS는 이것 하나뿐이라 맨 앞이다. 평가 순서 계약은
#: entry가 아니라 합성 루트의 import 그래프와 ``bootProduct`` 본문 순서가 진다.
BOOTSTRAP_ENTRY_POSITION = 0


def source_path(*parts: str) -> Path:
    """정적 프런트엔드 소스 루트 아래 경로를 돌려준다."""
    return SOURCE_ROOT.joinpath(*parts)


def source_text(*parts: str) -> str:
    """정적 프런트엔드 소스 파일을 UTF-8로 읽는다."""
    return source_path(*parts).read_text(encoding="utf-8")


def react_job_run_source() -> str:
    """실행·결과 React 후계 소스를 이어붙여 돌려준다 — 구 ``screens/job.js`` 등가."""
    return "".join(
        (SOURCE_ROOT / name).read_text(encoding="utf-8")
        for name in REACT_JOB_RUN_FILES
    )


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
    """제품 entry가 실을 JS import 경로를 실행 순서대로 조립한다."""
    legacy = [f"../js/{name}" for name in LEGACY_JS_FILES]
    return (
        *legacy[:BOOTSTRAP_ENTRY_POSITION],
        f"./{BOOTSTRAP_MODULE}",
        *legacy[BOOTSTRAP_ENTRY_POSITION:],
    )


def evaluated_modules(entry: str) -> tuple[str, ...]:
    """제품 entry의 JS import를 **평가 순서의 모듈 이름**으로 정규화한다.

    ``../js/X``는 ``X``로, 합성 루트는 ``bootstrap.js``로 읽는다. CSS import는 뺀다.

    :func:`side_effect_imports`가 아니라 :func:`module_imports`로 읽는 것이 N-10의 변화다.
    종전 entry는 합성 루트를 ``import "./compat.js";`` 부작용 import로 실었지만, 이제
    ``import { bootProduct } from "./bootstrap.js";``라 **named import**다. 부작용 형태만
    세는 눈으로 보면 합성 루트가 목록에서 조용히 사라지고, "entry가 아무 JS도 싣지 않는다"는
    거짓 초록이 난다 — :func:`module_imports` 독스트링이 경고하는 바로 그 창이다.
    """
    names: list[str] = []
    for path in module_imports(entry):
        if path.startswith("../js/"):
            names.append(path.removeprefix("../js/"))
        elif path == f"./{BOOTSTRAP_MODULE}":
            names.append(BOOTSTRAP_MODULE)
    return tuple(names)


def module_imports(source: str) -> tuple[str, ...]:
    """모듈이 정적으로 끌어오는 **모든** import 경로를 문서 순서대로 읽는다.

    :func:`side_effect_imports`는 ``import "x";`` 형태만 센다. ESM 전환이 진행되면서 모듈은
    ``import { X } from "x";``로 옮겨가는데, 그 둘을 같은 눈으로 보지 않으면 "entry 목록에서
    사라졌다"는 사실을 아무도 말하지 않는 창이 생긴다 — ``in`` 단언만 깨지고 ``not in``
    단언은 애초에 없기 때문이다. 세미콜론은 ASI 때문에 선택 사항이다. 도달성을 묻는 계약은
    이 함수로 물어야 한다.
    """
    return tuple(
        re.findall(
            r'(?m)^\s*import\s+(?:[^"\';]*?\s+from\s+)?["\']([^"\']+)["\']',
            source,
        )
    )


def bootstrap_imports() -> tuple[str, ...]:
    """합성 루트가 끌어오는 ``../js/`` 모듈 이름을 import 순서대로 읽는다."""
    prefix = "../js/"
    return tuple(
        path.removeprefix(prefix)
        for path in module_imports(SOURCE_BOOTSTRAP.read_text(encoding="utf-8"))
        if path.startswith(prefix)
    )


def reaches_product_graph(name: str) -> bool:
    """모듈이 제품 그래프에 **실제로 닿는지** 묻는다 — entry 직접이든 합성 루트 경유든.

    "이 파일이 앱에 실리는가"를 ``imported_js(entry)`` 로 묻던 계약들의 후계다. 그 질문은
    파일이 entry의 bare import 목록에 있는지를 봤는데, ESM으로 옮겨간 모듈은 그 목록에서
    사라지므로 같은 문자열 검사로는 "안 실린다"와 "이름이 옮겨졌다"를 구별하지 못한다.
    """
    if name in ESM_FILES:
        return name in bootstrap_imports() and BOOTSTRAP_MODULE in evaluated_modules(
            SOURCE_ENTRY.read_text(encoding="utf-8")
        )
    return name in imported_js(SOURCE_ENTRY.read_text(encoding="utf-8"))


def evaluation_site(name: str) -> str:
    """모듈 이름을 **제품 entry에서 실제로 평가되는 지점**의 이름으로 옮긴다.

    "공유 헬퍼가 소비 화면보다 먼저 실행되는가"를 묻던 계약들은 모듈 파일 이름을 entry
    순서에서 찾았다. N-04의 잎 넷과 N-05의 서비스 열다섯은 entry가 직접 싣지 않고 합성
    루트가 끌어오므로, 같은 질문의 답은 그 파일이 아니라 합성 루트의 자리에 있다. 이 함수가
    그 옮김을 한 곳에 둔다 — 각 테스트가 따로 ``bootstrap.js``를 하드코딩하면 다음 모듈이
    옮겨갈 때 조용히 낡는다.
    """
    return BOOTSTRAP_MODULE if name in ESM_FILES else name


# ── frontend module graph (SG-03 #735: 단일 출처) ────────────────────────────────
# ``test_p3_forbidden_edges`` 의 vendor 배치 게이트와 ``test_control_surface_reduction``
# 의 canonical-semantic import 게이트가 **같은** frontend import-graph 진실을 읽도록,
# specifier 추출·모듈 resolve·소스 census 를 여기 한 곳에 둔다(과거엔 forbidden-edges
# 파일에 살았다). 두 게이트가 각자 스캐너를 두면 넷째 소비자가 생길 때 조용히 갈라진다.
def _js_masks(source: str) -> tuple[str, str]:
    """주석만 지운 소스와 문자열/template raw까지 지운 동길이 code mask를 만든다."""
    commentless = list(source)
    code = list(source)
    size = len(source)

    def blank(buffer: list[str], start: int, end: int) -> None:
        for index in range(start, end):
            if source[index] not in "\r\n":
                buffer[index] = " "

    def quoted(start: int, quote: str) -> int:
        index = start + 1
        while index < size:
            if source[index] == "\\":
                index += 2
            elif source[index] == quote:
                return index + 1
            else:
                index += 1
        return size

    def template(start: int) -> int:
        blank(code, start, start + 1)
        index = start + 1
        while index < size:
            if source[index] == "\\":
                end = min(index + 2, size)
                blank(code, index, end)
                index = end
            elif source[index] == "`":
                blank(code, index, index + 1)
                return index + 1
            elif source.startswith("${", index):
                blank(code, index, index + 2)
                end = javascript(index + 2, stop_at_brace=True)
                if end and source[end - 1] == "}":
                    blank(code, end - 1, end)
                index = end
            else:
                blank(code, index, index + 1)
                index += 1
        return size

    def javascript(start: int, *, stop_at_brace: bool = False) -> int:
        index = start
        braces = 0
        while index < size:
            if source.startswith("//", index):
                end = index + 2
                while end < size and source[end] not in "\r\n":
                    end += 1
                blank(commentless, index, end)
                blank(code, index, end)
                index = end
            elif source.startswith("/*", index):
                closing = source.find("*/", index + 2)
                end = size if closing < 0 else closing + 2
                blank(commentless, index, end)
                blank(code, index, end)
                index = end
            elif source[index] in "\"'":
                end = quoted(index, source[index])
                blank(code, index, end)
                index = end
            elif source[index] == "`":
                index = template(index)
            elif stop_at_brace and source[index] == "}":
                if braces == 0:
                    return index + 1
                braces -= 1
                index += 1
            else:
                if stop_at_brace and source[index] == "{":
                    braces += 1
                index += 1
        return size

    javascript(0)
    return "".join(commentless), "".join(code)


def _frontend_specifiers(relative: str, source: str) -> tuple[str, ...]:
    raw = source
    source, code = _js_masks(raw)
    references = tuple(
        match.group(1)
        for match in re.finditer(
            r'''(?m)^\s*///\s*<reference\s+types\s*=\s*["']([^"']+)["']\s*/>''',
            raw,
        )
        if not source[match.start() : match.end()].strip()
    )
    dynamic: list[str] = []
    for call in re.finditer(r"(?<![\w$.])import\s*\(", code):
        literal = re.match(r'''\s*(["'])([^"'\\]+)\1\s*\)''', source[call.end() :])
        if literal is None:
            raise ContractError(
                f"{relative}: dynamic import() specifier는 문자열 literal이어야 합니다"
            )
        dynamic.append(literal.group(2))
    required: list[str] = []
    for call in re.finditer(r"(?<![\w$])(?:module\s*\.\s*)?require\s*\(", code):
        literal = re.match(r'''\s*(["'])([^"'\\]+)\1\s*\)''', source[call.end() :])
        if literal is None:
            raise ContractError(f"{relative}: require() specifier는 문자 literal이어야 합니다")
        required.append(literal.group(2))
    return (
        *references,
        *module_imports(source),
        *re.findall(
            r'''(?m)^\s*import\s+(?:type\s+)?[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*require\s*\(\s*["']([^"']+)["']\s*\)''',
            source,
        ),
        *re.findall(
            r'''(?m)^\s*export\s+(?:type\s+)?[^"\';]*?\s+from\s+["']([^"']+)["']''',
            source,
        ),
        *dynamic,
        *required,
    )


def _resolve_frontend_module(
    relative: str, specifier: str, sources: dict[str, str]
) -> str | None:
    clean = specifier.split("?", 1)[0].split("#", 1)[0]
    target = (
        posixpath.normpath(f"frontend{clean}")
        if clean.startswith("/")
        else posixpath.normpath(posixpath.join(posixpath.dirname(relative), clean))
    )
    suffixes = (
        ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
        ".d.ts", ".d.mts", ".d.cts",
    )
    candidates = (target, *(f"{target}{suffix}" for suffix in suffixes))
    candidates += tuple(f"{target}/index{suffix}" for suffix in suffixes)
    return next((candidate for candidate in candidates if candidate in sources), None)


def _frontend_sources(source_root: Path = SOURCE_ROOT) -> dict[str, str]:
    return {
        f"frontend/{path.relative_to(source_root).as_posix()}": path.read_text(encoding="utf-8")
        for directory in ("src", "js")
        for path in source_root.joinpath(directory).rglob("*")
        if path.suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
    }
