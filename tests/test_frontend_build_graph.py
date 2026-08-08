"""Vite build graph·물리 source transition(N-03 M1)과 잎 ESM 전이(N-04) 계약."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from _web_source import (
    ALL_CSS_FILES,
    BOOTSTRAP_EXPORT,
    BOOTSTRAP_MODULE,
    ESM_FILES,
    LEGACY_JS_FILES,
    PRODUCT_API_GLOBAL,
    RETIRED_COMPAT_GLOBALS,
    SOURCE_BOOTSTRAP,
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_JS_DIR,
    SOURCE_ROOT,
    bootstrap_imports,
    entry_js_manifest,
    evaluated_modules,
    module_imports,
    side_effect_imports,
    strip_comments,
)

ROOT = Path(__file__).resolve().parents[1]

NODE_VERSION = "24.18.1"
NPM_VERSION = "11.16.0"
VITE_VERSION = "8.1.5"
TYPESCRIPT_VERSION = "7.0.2"
REACT_VERSION = "19.2.8"
TYPES_REACT_VERSION = "19.2.18"
TYPES_REACT_DOM_VERSION = "19.2.4"

#: 제품 ``dependencies`` 정확-동등 핀 (R2-01 · #405). **bare specifier 허용 목록이 여기서
#: 유도된다** — package.json 에서 유도하면 「선언 한 줄 + import 한 줄」로 핀 빨강 없이
#: 의존이 조용히 열린다(L16 B4). 이 상수를 넓히는 diff 만이 의존을 넓힌다.
PINNED_DEPENDENCIES = {
    "react": REACT_VERSION,
    "react-dom": REACT_VERSION,
}

#: devDependencies 정확-동등 핀. ``@types/*`` 가 든 이유: React 19 는 자체 TS 타입을
#: 동봉하지 않아(착수 실측 — npm ``types`` 필드 부재), 이 둘 없이는 ``tsc --noEmit`` 이
#: 서지 않는다(rev3 §4.2-2).
PINNED_DEV_DEPENDENCIES = {
    "@types/react": TYPES_REACT_VERSION,
    "@types/react-dom": TYPES_REACT_DOM_VERSION,
    "typescript": TYPESCRIPT_VERSION,
    "vite": VITE_VERSION,
}


def _ts_bare_allowed(spec: str) -> bool:
    """``.ts`` 서브트리에만 허용되는 bare specifier — 핀 상수의 패키지와 그 하위 경로만.

    ``.js`` 도달 그래프는 이 함수를 거치지 않고 **bare 0 을 유지**한다 — 비 React JS가
    ``import "react"`` 를 싣는 경로의 원천 차단이다(L16 N4: ADR-06 「legacy 신규 기능
    금지」가 리뷰 계약에서 게이트 계약으로 올라온 자리).
    """
    return any(
        spec == package or spec.startswith(f"{package}/")
        for package in PINNED_DEPENDENCIES
    )

EXPECTED_CSS_FILES = {
    "base.css",
    "draftcard.css",
    "editor.css",
    "forced-colors.css",
    "job.css",
    "jobdata.css",
    "library.css",
    "overlay.css",
    "tail.css",
    "tokens.css",
}
#: ESM 모듈이 내는 공개 이름 — 파일당 정확히 하나. 평범한 named export와 factory가 섞여
#: 있고, 그 갈림은 자의가 아니다: 의존이 다른 ESM 모듈뿐이면 named export, 아직 전역인
#: ``Bridge``/``Nav``를 쓰거나 factory 산물을 주입받아야 하면 ``create*`` factory다.
EXPECTED_ESM_EXPORTS = {
    # N-04 잎 넷
    "copy.js": "Copy",
    "esc.js": "escHtml",
    "guard.js": "Guard",
    # N-05 서비스 — 포트가 필요 없어 모듈 평가가 곧 싱글턴인 일곱
    "popover.js": "Popover",
    "preserve.js": "Preserve",
    "intent.js": "Intent",
    "undo_toast.js": "UndoToast",
    "surface_sheet.js": "createSurfaceSheet",
    # N-07 브리지 — 마지막 IIFE. 산물 ``{bridge, push}`` 를 중앙이 한 번 구성해 나눠 준다.
    "bridge.js": "createBridge",
}

#: 자기 파일에서 자기 전역을 만드는 legacy IIFE 생산자 — N-07에서 **0개**가 됐다.
EXPECTED_LEGACY_GLOBALS: set[str] = set()

#: N-10이 지운 임시 전역 별칭 스물일곱. 이름을 **목록으로 남기는** 이유는 되살아나는 모양을
#: 이름으로 겨누기 위해서다: 수량만 세면 다른 이름의 새 전역이 생겨도 초록이고, 총량만
#: 0으로 두면 어느 이름이 돌아왔는지 실패 메시지가 말해 주지 못한다.
#:
#: N-04~N-07이 옮긴 것은 생산 **자리**였고 수량은 27로 불변이었다(D-05는 단조 감소만
#: 요구했다). N-10에서 그 수량이 0이 됐고, 이 상수는 이제 **금지 목록**이다.
EXPECTED_RUNTIME_GLOBALS: set[str] = set()

#: 되살아나면 안 되는 이름 전수 — 생산도 판독도 0이어야 한다.
FORBIDDEN_PRODUCT_GLOBALS = frozenset(RETIRED_COMPAT_GLOBALS)

#: R5-01(#419)에서 물리적으로 폐기한 마지막 셸/선호/overlay 파사드 경로.
#: 수량이 아니라 이름을 고정해야 다른 파일 하나가 지워진 자리를 대신해도 초록이 되지 않는다.
RETIRED_R5_MODULES = (
    "js/app.js",
    "js/theme.js",
    "js/personalization.js",
    "js/modal.js",
)


def strip_js_comments(source: str) -> str:
    """JS 원본에서 주석만 걷는다 — 문자열 리터럴 안의 ``//``·``/*`` 는 건드리지 않는다.

    이 저장소의 프런트 주석은 결정 근거를 길게 보존하고, 그 산문은 죽은 전역 이름을 일부러
    인용한다("종전에는 ``window.Nav`` 를 읽었다"). 그 인용을 코드로 세면 산문이 게이트를
    빨갛게 만들고, 결국 주석에서 이름을 지우는 압력이 생긴다 — 계약이 기억을 이기는 자리다.

    반대로 ``re.sub(r"//.*")`` 같은 순진한 제거는 ``"http://…"`` 의 뒤를 통째로 날려 **진짜
    판독을 숨긴다**. 음성 게이트에서 그 방향의 오차는 조용한 통과라 더 나쁘다. 그래서 문자열·
    템플릿·정규식 리터럴을 인지하는 최소 렉서로 걷는다. 과다 제거 여부는
    :func:`test_retired_compat_aliases_have_no_producer_and_no_reader` 의 양성 대조가 잰다.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
        elif ch == "/" and nxt == "*":
            i += 2
            while i < n and not (source[i] == "*" and source[i + 1 : i + 2] == "/"):
                i += 1
            i += 2
        elif ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            while i < n and source[i] != quote:
                if source[i] == "\\":
                    out.append(source[i])
                    i += 1
                if i < n:
                    out.append(source[i])
                    i += 1
            if i < n:
                out.append(source[i])
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _run_text(*command: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"명령이 실패했습니다: {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout.strip()


def _vite_config() -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, f"Node {NODE_VERSION}이 PATH에 없습니다"
    script = r"""
import path from "node:path";
import config from "./vite.config.mjs";

const relative = (value) => path.relative(process.cwd(), value).replaceAll("\\", "/");
console.log(JSON.stringify({
  root: relative(config.root),
  base: config.base,
  server: config.server,
  preview: config.preview,
  build: {
    outDir: relative(config.build.outDir),
    emptyOutDir: config.build.emptyOutDir,
    manifest: config.build.manifest,
    cssCodeSplit: config.build.cssCodeSplit,
    assetsInlineLimit: config.build.assetsInlineLimit,
    modulePreload: config.build.modulePreload,
    minify: config.build.minify,
    // sourcemap 은 **파일을 늘리지 않고도** 출하 바이트에 source 를 실을 수 있다
    // ('inline'). 산출물 구성 폐포(web_artifact._validate_output_composition)는 파일
    // 목록만 보므로 그 형태를 못 본다 — 그래서 형상 핀이 이 키를 든다(L16 반증, R5-03).
    sourcemap: config.build.sourcemap ?? false,
    treeshake: config.build.rolldownOptions?.treeshake,
  },
}));
"""
    return json.loads(_run_text(node, "--input-type=module", "--eval", script))


def test_exact_node_npm_vite_pins_are_locked() -> None:
    node = shutil.which("node")
    npm = shutil.which("npm.cmd")
    assert node is not None, f"Node {NODE_VERSION}이 PATH에 없습니다"
    assert npm is not None, f"bundled npm.cmd {NPM_VERSION}이 PATH에 없습니다"
    assert _run_text(node, "--version") == f"v{NODE_VERSION}"
    assert _run_text(npm, "--version") == NPM_VERSION

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert package["packageManager"] == f"npm@{NPM_VERSION}"
    assert package["engines"] == {"node": NODE_VERSION, "npm": NPM_VERSION}
    assert package["devDependencies"] == PINNED_DEV_DEPENDENCIES
    #: R2-01 이 신설한 런타임 의존 핀 — devDependencies 와 같은 형태의 정확 동등이다.
    #: 이 핀이 무는 한 「미핀 패키지 선언」은 여기서 빨갛고, 「선언 없는 import」는
    #: bare specifier 폐포에서 빨갛다 — 두 축이 합쳐져 조용한 의존 확장이 사라진다.
    assert package["dependencies"] == PINNED_DEPENDENCIES
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["devDependencies"] == PINNED_DEV_DEPENDENCIES
    assert lock["packages"][""]["dependencies"] == PINNED_DEPENDENCIES
    for name, version in (*PINNED_DEPENDENCIES.items(), *PINNED_DEV_DEPENDENCIES.items()):
        assert lock["packages"][f"node_modules/{name}"]["version"] == version, (
            f"lock 의 {name} 이 선언 핀 {version} 과 다릅니다 — uv.lock 규율의 npm 판입니다."
        )

    npmrc = (ROOT / ".npmrc").read_text(encoding="utf-8").splitlines()
    assert npmrc == ["engine-strict=true", "save-exact=true"]


def test_product_scripts_offer_build_only() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["type"] == "module"
    assert package["scripts"] == {
        "build": "vite build && uv run python scripts/seal_web_artifact.py",
        "verify:web": "uv run python scripts/seal_web_artifact.py --verify",
    }
    assert {"dev", "serve", "start", "preview"}.isdisjoint(package["scripts"])


def test_vite_production_graph_is_atomic_and_relative() -> None:
    config = _vite_config()

    assert config == {
        "root": "frontend",
        "base": "./",
        "build": {
            "outDir": "build/web",
            "emptyOutDir": True,
            "manifest": True,
            "cssCodeSplit": False,
            "assetsInlineLimit": 0,
            "modulePreload": False,
            "minify": False,
            "sourcemap": False,
            "treeshake": False,
        },
    }


def test_typescript_config_is_erasable_and_exactly_this() -> None:
    """tsconfig 는 **erasable syntax 전용**이고 형상은 딕셔너리 동등으로 잠근다.

    node 직접 적재(type stripping)와 형식 검사(``tsc --noEmit``)와 Vite 빌드가 **같은
    파일**을 보는 것이 R2-01 의 계약이다. ``erasableSyntaxOnly`` 가 그 등가를 지킨다 —
    enum·namespace 처럼 런타임 산출이 있는 TS 문법이 들어오면 node 적재와 tsc 가 갈린다.

    ``include`` 는 확장자 열거가 아니라 **경로 전체**다(#490 F2) — tsc 는 그 안에서
    TS-가족(``.ts``·``.tsx``·``.mts`` …)을 스스로 고르므로 새 확장자가 자동 편입된다.
    ``.tsx`` 는 이 단계에서 여전히 닫혀 있고 집행은 두 겹이다(착수 실측): **존재**는
    감산형 등재 핀이 문다(¬``.js`` 필터 — 미등재 ``.tsx`` 는 도달 불가여도 빨강),
    **JSX 문법**은 ``jsx`` 옵션 부재의 tsc 가 문다(JSX 없는 ``.tsx`` 는 tsc 만으로는
    초록이라 존재 축을 tsc 에 맡길 수 없다 — 그래서 등재 핀이 1차다). Node 24 가 ``.ts``
    만 싣는다는 실증은 패킷 rev2 L16 B2.
    """
    config = json.loads((ROOT / "tsconfig.json").read_text(encoding="utf-8"))

    assert config == {
        "compilerOptions": {
            "target": "ES2022",
            "module": "esnext",
            "moduleResolution": "bundler",
            "lib": ["ES2022", "DOM", "DOM.Iterable"],
            "strict": True,
            "noUnusedLocals": True,
            "noUnusedParameters": True,
            "noEmit": True,
            "erasableSyntaxOnly": True,
            "verbatimModuleSyntax": True,
            "allowImportingTsExtensions": True,
            "useDefineForClassFields": True,
            "forceConsistentCasingInFileNames": True,
            "skipLibCheck": False,
            "types": [],
        },
        "include": ["frontend/src/**/*"],
    }


def test_typescript_sources_pass_the_type_check() -> None:
    """``tsc --noEmit`` 초록 — 형식 검사가 게이트 안에서 실제로 돈다.

    별도 스크립트로 두면 `test.ps1` 과 CI 잡 중 아무도 부르지 않는 채 초록일 수 있다 —
    node 모듈 단위 게이트를 pytest 가 직접 모는 것과 같은 논거로 여기서 돈다.
    """
    node = shutil.which("node")
    assert node is not None, f"Node {NODE_VERSION}이 PATH에 없습니다"
    tsc = ROOT / "node_modules" / "typescript" / "bin" / "tsc"
    assert tsc.is_file(), (
        "잠긴 typescript 가 설치돼 있지 않습니다 — `npm ci` 가 이 게이트의 전제입니다."
    )

    _run_text(node, str(tsc), "-p", str(ROOT / "tsconfig.json"))


def test_frontend_is_the_only_physical_source_tree() -> None:
    config = _vite_config()

    assert config["root"] == SOURCE_ROOT.relative_to(ROOT).as_posix()
    assert SOURCE_ROOT.is_dir()
    assert SOURCE_ROOT.name == "frontend"
    assert "web" not in {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert {path.name for path in (SOURCE_ROOT / "css").glob("*.css")} == (
        EXPECTED_CSS_FILES
    )


def test_product_entry_is_one_module_with_ordered_side_effect_graph() -> None:
    """entry 는 module script 하나이고, CSS 캐스케이드 순서를 부작용 import 로 고정한다.

    JS 쪽은 N-10 에서 형태가 바뀌었다: 합성 루트는 이제 부작용 import 가 아니라 **named
    import + 호출**이라 :func:`side_effect_imports` 에 잡히지 않는다. 그래서 CSS 순서는
    부작용 목록으로, JS 도달은 :func:`evaluated_modules` 로 각각 묻는다 — 한 눈으로 보면
    "JS 가 아예 없다"와 "형태가 바뀌었다"가 구별되지 않는다.
    """
    html = SOURCE_INDEX.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*\bsrc=\"[^\"]+\"[^>]*></script>", html)

    assert scripts == ['<script type="module" src="./src/main.js"></script>']

    entry = SOURCE_ENTRY.read_text(encoding="utf-8")
    #: 부작용 import 는 이제 CSS 전수뿐이다 — 순서가 곧 캐스케이드 계약이다.
    assert side_effect_imports(entry) == tuple(
        f"../css/{name}" for name in ALL_CSS_FILES
    )
    #: JS 도달은 형태를 가리지 않는 눈으로 따로 묻는다(named import 도 세는 쪽).
    assert tuple(
        path for path in module_imports(entry) if not path.startswith("../css/")
    ) == entry_js_manifest()


def test_converted_modules_are_esm_and_own_no_globals() -> None:
    """남은 JS ESM 9개는 IIFE도 전역 생산자도 아니고 자기 공개 이름 하나만 낸다.

    M1의 "25 IIFE 전수"를 이 후계가 잇는다. 여기서 수량만 세면 모듈이 export를 내면서
    ``window.SegView`` 도 같이 남기는 이중 유지가 통과한다 — 그래서 파일별로 IIFE 0,
    자기 전역 write 0, 정확한 export 이름을 함께 단언한다.

    잎 넷과 달리 서비스 다섯은 표준 Web API(``window.addEventListener``·``window.alert``·
    ``window.pywebview`` 등)를 정당하게 쓴다. 그래서 "``window.`` 문자열 0"으로는 셀 수 없고,
    금지 대상은 **제품 전역 이름**이다. 그 목록은 N-10에서 사라진 별칭 스물일곱
    (:data:`FORBIDDEN_PRODUCT_GLOBALS`)이다 — 별칭이 죽었어도 **판독**이 되살아나면 그
    모듈은 영영 `undefined` 를 읽고 조용히 아무것도 안 한다.
    """
    assert set(EXPECTED_ESM_EXPORTS) == set(ESM_FILES)
    assert len(ESM_FILES) == 9

    #: 양성 대조 — 금지 목록이 비면 아래 정규식이 무엇에도 맞지 않아 게이트가 조용히 통과한다.
    assert len(FORBIDDEN_PRODUCT_GLOBALS) == 27

    product_globals = re.compile(
        r"\b(?:window|globalThis)\.(?:"
        + "|".join(sorted(map(re.escape, FORBIDDEN_PRODUCT_GLOBALS)))
        + r")\b"
    )

    for name in ESM_FILES:
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\(function \(\) \{", source), (
            f"{name} 이 아직 IIFE 로 감싸져 있습니다 — N-04·N-05 는 true ESM 입니다."
        )
        assert not re.search(
            r"(?m)^\s*(?:window|globalThis)\.[A-Za-z_$][A-Za-z0-9_$]*\s*=", source
        ), f"{name} 이 자기 전역을 만듭니다 — 제품 전역은 합성 루트의 `__hwpx` 하나뿐입니다."
        leaked = product_globals.findall(source)
        assert not leaked, (
            f"{name} 이 제품 전역을 직접 조회합니다: {sorted(set(leaked))} — "
            "의존은 import 나 명시적 주입으로 드러나야 합니다."
        )
        assert "Object.assign(window" not in source.replace(" ", ""), (
            f"{name} 이 window 에 일괄 대입합니다."
        )
        exported = set(
            re.findall(
                r"(?m)^export\s+(?:const|let|var|function|class)\s+"
                r"([A-Za-z_$][A-Za-z0-9_$]*)",
                source,
            )
        )
        assert exported == {EXPECTED_ESM_EXPORTS[name]}, (
            f"{name} 의 공개 표면이 {sorted(exported)} 입니다 — "
            f"{EXPECTED_ESM_EXPORTS[name]} 하나여야 합니다."
        )
        assert "export default" not in source, f"{name} 이 default export 를 냅니다."


def test_r5_retired_shell_and_overlay_modules_are_physically_absent() -> None:
    """#419 삭제 경로가 이름 그대로 되살아나는 회귀를 막는다."""
    survivors = [relative for relative in RETIRED_R5_MODULES if (SOURCE_ROOT / relative).exists()]
    assert not survivors, f"R5 폐기 모듈이 되살아났습니다: {survivors}"


def test_service_dependencies_are_written_edges_not_global_lookups() -> None:
    """서비스 간·잎 의존이 **그래프에 적힌 단방향 간선**이다(암묵 로드 순서의 후계).

    N-05 전에는 ``modal.js`` 가 ``window.Popover`` 를, 다섯 파일이 ``window.escHtml`` 을
    모듈 로드 시점에 붙들었다. 그 계약들은 "누가 먼저 실리는가"를 entry 순서에서 물었는데,
    그 질문은 이제 import 문 자체가 답한다.
    """
    expected_edges = {
        "surface_sheet.js": set(),
        # R4-02 — 이동 다이얼로그·접힘 토글이 React 후계로 떠나며 esc·modal 간선도 함께 죽었다.
    }

    for name, expected in expected_edges.items():
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        actual = {path for path in module_imports(source) if path.startswith(".")}
        assert actual == expected, (
            f"{name} 의 모듈 간선이 {sorted(actual)} 입니다 — {sorted(expected)} 여야 합니다."
        )

    #: 간선이 없어야 하는 모듈은 정말 없어야 한다(잎다움의 음성 대조).
    for name in ("copy.js", "esc.js", "guard.js", "popover.js", "preserve.js",
                 "intent.js", "undo_toast.js"):
        source = (SOURCE_JS_DIR / name).read_text(encoding="utf-8")
        assert not [p for p in module_imports(source) if p.startswith("./")], (
            f"{name} 이 다른 제품 모듈을 import 합니다 — 잎이 아니게 됐습니다."
        )


def test_esm_module_graph_has_no_cycles() -> None:
    """제품 모듈 그래프에 순환이 0이다.

    N-05 의 순환 후보는 ``editor_entry ↔ app`` 하나였고, N-06 에서 화면 넷이 그래프에
    들어오며 ``editor ↔ job``·``library → job``·화면→Nav 가 새 후보로 늘었다. 그 간선들은
    전부 합성 루트의 late-bound 콜백 테이블이 그래프 밖에서 지므로 여기서 0이 나온다 —
    화면이 서로를(또는 앱 셸을) import 하는 구현으로 되돌아가면 이 게이트가 잡는다.
    """
    from posixpath import dirname, join, normpath

    graph = {
        name: [
            normpath(join(dirname(name), path))
            for path in module_imports((SOURCE_JS_DIR / name).read_text(encoding="utf-8"))
            if path.startswith(".")
        ]
        for name in ESM_FILES
    }
    graph[BOOTSTRAP_MODULE] = list(bootstrap_imports())

    seen: dict[str, int] = {}

    def visit(node: str, trail: tuple[str, ...]) -> None:
        if seen.get(node) == 1:
            raise AssertionError(f"import 순환: {' -> '.join((*trail, node))}")
        if seen.get(node) == 2:
            return
        seen[node] = 1
        for nxt in graph.get(node, ()):
            visit(nxt, (*trail, node))
        seen[node] = 2

    for name in graph:
        visit(name, ())


def test_segview_imports_the_escaper_instead_of_reading_a_global() -> None:
    """세그먼트 페인터는 R4-02 에서 React 로 옮겨졌다 — 이스케이프의 소유자가 바뀌었다.

    legacy 는 `escHtml` 을 ESM import 해 문자열을 조립했다(로드 순서 암묵 계약의 후계).
    후계는 요소 트리라 이스케이프를 React 가 태운다 — 그래서 이 가드가 지키는 것은 「로컬
    이스케이퍼를 다시 만들지 않았는가」다. 산출 동등성은 `tests/js/segview.test.js` 가 잰다.
    """
    source = (SOURCE_ROOT / "src" / "screens" / "segment_view.ts").read_text(encoding="utf-8")

    assert "createElement" in source, "세그먼트 후계가 요소 트리를 만들지 않습니다."
    assert "escHtml" not in source and "replace(/[&<>" not in source, (
        "React 후계가 로컬 이스케이퍼를 다시 들였습니다 — 이스케이프는 React 소유입니다."
    )


def test_retired_compat_aliases_have_no_producer_and_no_reader() -> None:
    """임시 별칭 스물일곱은 **생산도 판독도 0**이다 — compat 계층의 종착점(N-10).

    이 게이트의 전신은 ``test_temporary_aliases_have_exactly_one_central_producer`` 로,
    "별칭 스물여덟이 정확히 한 파일에서만 만들어지는가"를 물었다(D-05 단일 생산자). 단일
    생산자는 **수량을 셀 수 있게 하려고** 세운 규율이었고, 수량이 0이 된 지금 그 질문은
    "아무도 만들지 않는가"로 바뀐다. 세는 자리도 한 파일에서 ``frontend/`` 전수로 넓어진다 —
    생산자가 하나여야 할 이유가 사라졌으므로 이제는 **어디에도 없어야** 하기 때문이다.

    판독까지 함께 세는 것이 전신과 다른 점이다. 별칭 대입만 지우면 소비자는 `undefined` 를
    읽고 **조용히 아무것도 하지 않는다** — 예외도 안 난다. 그 침묵이 정확히 이 저장소가
    금지하는 실패 모양이라(confirm-or-alarm) 판독 0을 같은 게이트가 진다.
    """
    #: 양성 대조 — 목록이 비면 아래 루프가 아무것도 겨누지 않은 채 초록이 된다.
    assert len(FORBIDDEN_PRODUCT_GLOBALS) == 27
    assert PRODUCT_API_GLOBAL not in FORBIDDEN_PRODUCT_GLOBALS

    #: 스캐너 자체의 양성·음성 대조. 주석 인용은 넘기되 **실제 판독은 반드시 잡아야** 하고,
    #: 문자열 안의 ``//`` 뒤가 통째로 사라지면 그 뒤의 진짜 판독이 숨는다. 두 방향을 한
    #: 표본에서 함께 잰다 — 부재를 재는 게이트는 자기 눈부터 증명해야 한다.
    probe = strip_js_comments(
        '// 종전에는 window.Nav 를 읽었다\n'
        '/* window.Bridge 도 여기 있었다 */\n'
        'const u = "http://x/y"; window.Modal.open();\n'
    )
    assert re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)", probe) == ["Modal"], (
        f"전역 스캐너의 눈이 어긋났습니다: {probe!r}"
    )

    #: 공유 수집 집합(`.js`+`.ts`)을 소비한다 — 별칭의 생산·판독은 파일 형식을 가리지 않는다.
    sources = {
        name: strip_js_comments(text) for name, text in _frontend_sources().items()
    }
    #: 부재를 재기 전에 **실제로 읽었는가**를 먼저 잰다(계측 층의 부재판별력).
    assert len(sources) >= 25, f"프런트 소스를 {len(sources)}개만 읽었습니다 — 스캔이 헛돕니다."

    produced = {
        f"{name}:{alias}"
        for name, source in sources.items()
        for alias in re.findall(
            r"(?m)^\s*(?:window|globalThis)\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", source
        )
        if alias in FORBIDDEN_PRODUCT_GLOBALS
    }
    assert not produced, (
        "은퇴한 임시 전역 별칭이 되살아났습니다: " + ", ".join(sorted(produced))
    )

    read = {
        f"{name}:{alias}"
        for name, source in sources.items()
        for alias in re.findall(
            r"\b(?:window|globalThis)\.([A-Za-z_$][A-Za-z0-9_$]*)\b", source
        )
        if alias in FORBIDDEN_PRODUCT_GLOBALS
    }
    assert not read, (
        "은퇴한 전역 별칭을 아직 판독합니다(값은 undefined — 조용히 아무것도 안 합니다): "
        + ", ".join(sorted(read))
    )

    #: 합성 루트가 만드는 전역은 제품 공개 API 하나뿐이다(D-06).
    bootstrap_source = SOURCE_BOOTSTRAP.read_text(encoding="utf-8")
    assert SOURCE_BOOTSTRAP.name == BOOTSTRAP_MODULE
    producers = re.findall(
        r"(?m)^\s*window\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", bootstrap_source
    )
    assert producers == [PRODUCT_API_GLOBAL], (
        f"합성 루트가 만드는 전역이 {producers} 입니다 — {PRODUCT_API_GLOBAL} 하나여야 합니다."
    )
    assert set(bootstrap_imports()) == set(ESM_FILES), (
        "합성 루트의 import 집합이 ESM 모듈 전수와 어긋납니다 — 구성에서 빠진 모듈이 있습니다."
    )

    #: `compat.js` 는 이름째 은퇴했다 — 별칭 줄만 지우고 파일을 남기면 "호환 계층이 아직
    #: 있다"는 거짓 표식이 남고, 다음 임시 전역이 조용히 그리로 돌아온다.
    assert not (SOURCE_ROOT / "src" / "compat.js").exists()
    dangling = sorted(
        name for name, source in sources.items() if "compat.js" in source
    )
    assert not dangling, f"삭제된 compat.js 를 아직 참조합니다: {dangling}"


def test_each_service_is_constructed_exactly_once_in_the_composition_root() -> None:
    """포트를 받는 factory 열넷(서비스 8 + 화면 4 + 앱 셸 + 브리지)은 **정확히 한 번** 불린다.

    두 번 부르면 ``pathtrack`` 의 위임 리스너가 겹치고 ``data_picker`` 의 ``onPush`` 가
    누적되며, 화면·앱 셸은 DOM 리스너와 부팅 랜딩이 두 벌이 된다. 모듈 안에 재호출 가드를
    두는 대신 호출 자리를 하나로 묶었으므로, 그 단일성은 여기서 세야 한다.

    N-10 에서 달라진 것은 **단일성의 근거**다. 종전에는 합성이 모듈 평가라 ESM 캐시가
    한 번을 보장했다. 이제 합성은 ``bootProduct()`` 호출이고, 그 함수는 멱등이 아니다 —
    한 번을 보장하는 것은 **호출자가 하나뿐이라는 사실**이라
    :func:`test_entry_calls_the_composition_root_exactly_once` 가 그 축을 따로 진다.
    """
    #: 이 파일의 헤더 주석은 ``Nav`` 를 값으로 붙들면 안 되는 **이유**를 적는다.
    #: 그 산문을 코드로 세면 "판독이 한 곳뿐인가"라는 질문이 주석 길이에 좌우된다.
    compat_source = strip_comments(SOURCE_BOOTSTRAP.read_text(encoding="utf-8"))
    factories = sorted(
        export for name, export in EXPECTED_ESM_EXPORTS.items()
        if export.startswith("create")
    )

    assert len(factories) == 2
    for factory in factories:
        calls = re.findall(rf"\b{re.escape(factory)}\s*\(", compat_source)
        assert len(calls) == 1, (
            f"합성 루트가 {factory} 를 {len(calls)}회 부릅니다 — 정확히 1회여야 합니다."
        )

    for factory in ("createTheme", "createPersonalization", "createAppShell", "createModal"):
        calls = re.findall(rf"\b{re.escape(factory)}\s*\(", compat_source)
        assert len(calls) == 1, (
            f"합성 루트가 TS 셸 factory {factory} 를 {len(calls)}회 부릅니다 — 정확히 1회여야 합니다."
        )

    # R4-01에서 legacy factory 셋은 React controller/runtime/port 합성으로 교체됐다. 이들은
    # EXPECTED_ESM_EXPORTS(legacy JS 파일당 단일 export 계정) 밖이므로 별도 전수로 단일성을 센다.
    r4_factories = (
        "createScreenRuntime", "createScreenPorts", "createServiceHandoffPorts",
        "createLibraryController", "createDataPickerController", "createJobReadController",
        # R4-02·R4-03 — 편집·매핑과 실행·결과의 controller/port 도 같은 규율을 받는다.
        "createEditorController", "createWorkbenchController", "createEditorEntry",
        "createJobRunController", "createJobRelink",
        # R4-04 — 단일 화면 트리 visibility/lifecycle/executor 결속.
        "createProductScreenVisibility", "createScreenLifecycleRegistry",
        "createProductScreenExecutor",
    )
    for factory in r4_factories:
        calls = re.findall(rf"\b{re.escape(factory)}\s*\(", compat_source)
        assert len(calls) == 1, (
            f"합성 루트가 R4 {factory} 를 {len(calls)}회 부릅니다 — 정확히 1회여야 합니다."
        )

    #: `navigate` 는 지연 호출 콜백이다 — N-05 의 `window.Nav` 판독은 Nav 생산이 합성 루트로
    #: 들어오며(N-06) 지역 late-bound 참조로 좁혀졌다. 값으로 캡처하면 앱 셸 구성 전의
    #: `undefined` 를 붙든다.
    assert re.search(r"const navigate = \(\.\.\.args\) => Nav\.go\(\.\.\.args\);",
                     compat_source), "navigate 가 지연 호출 콜백이 아닙니다."
    #: 전역 경유 판독은 0이다 — 되살아나면 순환이 그래프 밖으로 숨는다. 종전에는 별칭 대입
    #: 한 줄이 남아 `count == 1` 이었고, N-10 이 그 줄을 지우면서 기대값이 0이 됐다.
    assert compat_source.count("window.Nav") == 0
    #: `bridge` 는 이제 compat 이 **구성**한다(N-07) — 구 IIFE 를 되읽던 자리의 후계다.
    #: 객체째 넘기는 성질은 그대로여야 한다: 메서드를 뽑으면 selftest 프로브의 스텁 교체가
    #: 우회된다. 그래서 산물을 그대로 받는 구조분해 한 줄인지 본다.
    #:
    #: N-09 에서 시험 전용 호스트 통로 `testHost` 가 같은 산물에 합류했다. `bridge` 에 **얹지
    #: 않는** 것이 계약이라(얹으면 화면 넷·서비스 열다섯이 시험 능력을 부를 수 있게 되고
    #: "제품에서 도달 불가"가 표면 하나 차이로 무너진다) factory 의 별도 반환값으로 받는다.
    assert re.search(r"const \{ bridge, push, testHost \} = createBridge\(\);", compat_source)
    #: 전역 경유 판독·생산 둘 다 0이다. 종전에는 별칭 대입 한 줄이 남아 `count == 1` 이었고, 그 옆의
    #: 「별칭 이외 판독 0」 단언은 정규식에 `` 대신 **백스페이스 바이트(0x08)** 가 들어가
    #: 있어 아무것도 매치하지 못하는 **공허한 단언**이었다 — 선언은 살고 결과는 죽어 있던 자리다.
    assert compat_source.count("window.Bridge") == 0

    #: 교차 화면·Nav 콜백 테이블은 지연 호출이어야 한다 — 메서드를
    #: 프로퍼티로 뽑아 저장)로 되돌아가면 구성 순서에 따라 undefined 를 붙든다.
    for member in ("refreshList", "openBrowseNeedsAction"):
        assert re.search(
            rf"{member}: \(\.\.\.args\) => screenPorts\.jobRead\.current\(\)\.{member}\(\.\.\.args\),",
            compat_source,
        ), f"jobCallbacks.{member} 가 지연 호출 콜백이 아닙니다."
    assert "openPreview: (_event, options = {}) => screenPorts.jobRun.current().openPreview({" in compat_source
    assert re.search(
        r"aimAt: \(\.\.\.args\) => EditorController\.aimAt\(\.\.\.args\),", compat_source
    ), "editorCallbacks.aimAt 가 지연 호출 콜백이 아닙니다."
    for member in ("go", "refresh"):
        assert re.search(
            rf"{member}: \(\.\.\.args\) => Nav\.{member}\(\.\.\.args\),", compat_source
        ), f"navigation.{member} 가 지연 호출 콜백이 아닙니다."

    #: 제품 API 설치는 **모든 구성 뒤**에 선다 — 구성 전에 걸면 미구성 값이 공개 경계에
    #: 실리고 Python 소비자가 조용히 빈 통로를 읽는다(선언-사용 순서 계약의 후계).
    #:
    #: 종전에는 같은 질문을 **별칭 스물다섯**에 물었다(가장 먼저 서는 별칭이 마지막 구성보다
    #: 뒤인가). 별칭이 사라지면서 순서 계약이 걸릴 자리는 이 한 줄만 남았다 — 질문은 그대로고
    #: 대상만 줄었다.
    last_construction = max(
        compat_source.rindex(f"{factory}(") for factory in (*factories, *r4_factories)
    )
    api_install = compat_source.index(f"window.{PRODUCT_API_GLOBAL} =")
    assert last_construction < api_install, (
        "제품 API 설치가 factory 구성보다 먼저 섭니다 — 미구성 값이 공개 경계에 걸립니다."
    )
    #: 시험 배선은 제품 API 설치보다 **뒤**다. 앞에 서면 프로브가 아직 없는 파사드를 붙든다.
    assert api_install < compat_source.index("bootSelftest("), (
        "시험 배선이 제품 API 설치보다 먼저 섭니다."
    )


def test_no_legacy_iife_remains_and_temporary_global_surface_is_zero() -> None:
    """IIFE 는 **0개**이고, 임시 제품 전역 표면도 이제 **0개**다.

    M1 의 "25 IIFE / 27 globals" 계약이 여기서 끝난다. N-04~N-07 은 생산 **자리**만 옮겨
    수량 27 을 보존했고(D-05 는 단조 감소만 요구했다), N-10 이 그 27 을 0 으로 만들었다.

    제품 공개 API ``__hwpx`` 는 이 수량에 **들지 않는다** — 임시 별칭이 아니라 남는 최종
    경계라 계정이 다르다(D-06). 같은 자루에 넣었다면 D-05 의 계측점이 최종 API 하나 때문에
    영영 0 에 닿지 못했을 것이다.
    """
    scripts = tuple(sorted(SOURCE_JS_DIR.rglob("*.js")))
    non_esm = tuple(
        path
        for path in scripts
        if path.relative_to(SOURCE_JS_DIR).as_posix() not in ESM_FILES
    )

    assert len(scripts) == 9
    assert non_esm == ()
    assert LEGACY_JS_FILES == ()
    assert EXPECTED_LEGACY_GLOBALS == set()

    #: IIFE 래퍼는 프런트 소스 어디에도 없다 — 파일 전수로 센다(잔존 하나가 숨지 못하게).
    iife_owners = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in scripts
        if re.search(r"(?m)^\(function \(\) \{", path.read_text(encoding="utf-8"))
    }
    assert iife_owners == set(), f"IIFE 가 남아 있습니다: {sorted(iife_owners)}"

    assert EXPECTED_RUNTIME_GLOBALS == set()
    assert PRODUCT_API_GLOBAL not in EXPECTED_RUNTIME_GLOBALS


def test_entry_calls_the_composition_root_exactly_once() -> None:
    """제품 entry 의 JS 는 ``bootstrap.js`` **하나**이고, 부팅 호출도 **한 번**이다.

    "compat 이 모든 소비 IIFE 보다 먼저 평가된다"던 계약의 종착점이다. 소비 IIFE 가 전부
    ESM 이 되어 entry 에서 사라졌고, N-07 에서 마지막 하나(``bridge.js``)마저 합성 루트의
    static import 로 들어오면서 **entry 에 걸린 평가 순서 계약 자체가 없어졌다**. 남은
    순서 질문은 전부 합성 루트 안에 있다:
    :func:`test_each_service_is_constructed_exactly_once_in_the_composition_root` 과
    :func:`test_esm_module_graph_has_no_cycles` 가 진다.

    N-10 이 여기 더한 축이 **호출 횟수**다. 종전 entry 는 ``import "./compat.js";`` 부작용
    import 라 ESM 캐시가 "본문은 한 번만 돈다"를 공짜로 보장했다. 이제 부팅은
    ``bootProduct()`` 호출이고 그 함수는 멱등이 아니다 — 두 번 부르면 위임 리스너가 한 벌
    더 서고 부팅 랜딩이 두 번 찍힌다. 공짜였던 보장이 사라졌으므로 그 자리를 이 단언이 갚는다.

    화면·서비스가 entry 에 직접 남아 있으면 모듈이 두 경로로 그래프에 들어오므로 그 부재도
    같이 본다.
    """
    entry = SOURCE_ENTRY.read_text(encoding="utf-8")
    modules = evaluated_modules(entry)

    assert modules == (BOOTSTRAP_MODULE,)
    assert not set(modules) & set(ESM_FILES)

    #: named import 로 들여와 **정확히 한 번** 부른다.
    assert re.search(
        rf'(?m)^import\s+\{{\s*{BOOTSTRAP_EXPORT}\s*\}}\s+from\s+"\./{BOOTSTRAP_MODULE}";$',
        entry,
    ), f"entry 가 {BOOTSTRAP_EXPORT} 를 named import 하지 않습니다."
    code = strip_js_comments(entry)
    calls = re.findall(rf"(?m)^\s*{BOOTSTRAP_EXPORT}\(\);?\s*$", code)
    assert len(calls) == 1, (
        f"entry 가 {BOOTSTRAP_EXPORT} 를 {len(calls)}회 부릅니다 — 정확히 1회여야 합니다."
    )

    #: 정확한 줄 모양만 세면 `void bootProduct();`·`queueMicrotask(bootProduct)`
    #: 같은 두 번째 실행 경로가 위의 호출 수를 피한다. 합성 루트는 비멱등이므로
    #: 제품 소스 전체의 **식별자 참조 수**를 함께 못박는다: 정의 1 + import 1 + 호출 1.
    #: 공유 수집 집합을 소비하므로 신설 `.ts` 의 참조도 같은 자격으로 계수에 든다 —
    #: `.ts` 가 두 번째 실행 경로가 되는 모양을 여기서 막는다(rev3 §4.2-1).
    references = {
        name: len(
            re.findall(
                rf"\b{re.escape(BOOTSTRAP_EXPORT)}\b",
                strip_js_comments(text),
            )
        )
        for name, text in _frontend_sources().items()
    }
    references = {name: count for name, count in references.items() if count}
    assert references == {"src/bootstrap.js": 1, "src/main.js": 2}, (
        f"합성 루트 식별자 참조가 {references} 입니다 — "
        "bootstrap 정의 1회 + entry import/호출 각 1회만 허용됩니다."
    )

    #: 검출력 양성 대조 — 줄 머리가 다른 추가 호출도 참조 축은 반드시 본다.
    mutated = code + f"\nvoid {BOOTSTRAP_EXPORT}();\n"
    assert len(re.findall(rf"\b{re.escape(BOOTSTRAP_EXPORT)}\b", mutated)) == 3


# --------------------------------------------------------------- N-09 시험 능력 경계
#: 시험 능력의 전역 이름. 임시 별칭 27과도, 제품 공개 API ``__hwpx``와도 **다른 세 번째
#: 계정**이다: 임시 별칭이 아니므로 D-05의 단조 감소 계측에 들지 않고, 제품 표면이 아니므로
#: 정상 실행에는 **존재해서는 안 된다**.
SELFTEST_API_GLOBAL = "__hwpxTest"

#: 그 전역을 만드는 유일한 자리. ``Object.defineProperty``라 ``window.X =`` 정규식을 쓰는
#: 별칭 게이트에는 **잡히지 않는다** — 그래서 이 계정은 자기 게이트를 따로 가진다.
SELFTEST_API_PRODUCER = "src/selftest/api.js"


#: 정적 폐포 계약의 단일 출처(#490) — 수집 감산 목록과 예약 전역 가족·allowlist 를
#: node 쪽 AST 게이트(tests/js/pywebview_allowlist.test.js)와 **같은 파일**에서 읽는다.
STATIC_CLOSURE_CONTRACT = json.loads(
    (ROOT / "tests" / "static_closure_contract.json").read_text(encoding="utf-8")
)


def _frontend_sources() -> "dict[str, str]":
    """``frontend/`` 아래 코드 원본 **전수** — 소스-축 술어 전부가 소비하는 단일 수집 집합.

    수집은 확장자 **열거가 아니라 감산**이다(#490 F2): ``frontend/**`` 전 파일에서 계약의
    ``non_code_suffixes``(코드 술어가 읽지 않는 형식의 명시 제외)만 뺀다. 그래서 새 코드
    형식(``.tsx``·``.mts`` …)은 등재 없이 **자동 편입**되고 — 편입된 뒤 `.js` 아닌 파일은
    아래 정확-집합 핀이 등재를 요구한다 — 텍스트가 아닌 새 형식은 여기서 시끄럽게
    실패한다(코드가 아니면 계약에 명시 등재하라는 강제). 「집합 하나를 넓히고 형제를 안
    넓힌다」 결함류(`.js` 에 `.ts` 를 더할 때 `.tsx` 를 안 더한 자리)를 형식 자체로 없앤다.
    """
    excluded = set(STATIC_CLOSURE_CONTRACT["non_code_suffixes"])
    sources: "dict[str, str]" = {}
    for path in sorted(SOURCE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix in excluded:
            continue
        rel = path.relative_to(SOURCE_ROOT).as_posix()
        try:
            sources[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise AssertionError(
                f"{rel}: 텍스트로 읽히지 않는 형식입니다 — 코드가 아니면 "
                "tests/static_closure_contract.json 의 non_code_suffixes 에 명시 등재하세요."
            ) from error
    return sources


def test_the_shared_scan_set_actually_collects_the_ts_subtree() -> None:
    """수집 집합의 부재판별력 — `.ts` 를 실제로 걷는다는 사실을 먼저 세운다.

    이것이 없으면 아래 음성 술어들의 「위반 0」은 `.ts` 를 한 장도 안 읽은 초록과
    구별되지 않는다(계측 층의 부재판별력).
    """
    sources = _frontend_sources()
    #: 필터도 감산형이다(#490 F2) — 「`.ts` 만」이 아니라 「`.js` 아닌 전부」. 수집이
    #: 감산이라 새 코드 형식(`.tsx` 등)은 자동 편입되고, 여기 정확-집합에 등재되기 전엔
    #: **존재 자체가 빨강**이다(도달 불가 파일이 전 정적 축의 사각에서 자라는 경로 차단).
    ts_members = sorted(name for name in sources if not name.endswith(".js"))

    #: 등재 지점 — 새 단계의 `.ts` 는 여기 행 추가로 편입된다(R2 패킷 §4.3 의 규정과 같다).
    assert ts_members == [
        "src/contract/contract.gen.ts",  # R2-02 — 생성 계약(정본은 Python 실물)
        "src/overlay/engine.ts",  # R3-01 — 트리-불가지 overlay 판정(스택·직렬화·트랩·복귀)
        "src/overlay/host.ts",  # R3-01 — React host: 데이터-구동 표면 4 의 렌더·명령형 집행
        "src/overlay/instance.ts",  # R3-01 — 엔진 단일 인스턴스·다이얼로그 host 슬롯·keydown 배선
        "src/ports/service_handoff.ts",  # R4-01 — legacy 서비스의 typed handoff 슬롯
        "src/react/boot.ts",
        "src/react/boundary.ts",
        "src/react/root.ts",
        "src/runtime/adapter.ts",  # R2-02 — pywebview 접촉의 유일한 신규 소유자
        "src/runtime/client.ts",  # R2-02 — 생성 유니온으로 좁혀진 전송 표면
        "src/screens/context_menu.ts",  # R4-04 — React 문맥 메뉴 상태·Popover 배치
        "src/screens/data_picker.ts",  # R4-01 — 데이터 선택·등록 React producer/controller
        "src/screens/data_zone.ts",  # R4-01 — job 데이터 표 React producer
        "src/screens/editor.ts",  # R4-02 — 편집기 React controller/producer
        "src/screens/editor_entry.ts",  # R4-02 — 편집기 진입/복귀 초점 seam
        "src/screens/editor_state.ts",  # R4-02 — 전송 스냅샷↔local draft reducer
        "src/screens/group_move_dialog.ts",  # R4-02 — 템플릿 그룹 이동 다이얼로그
        "src/screens/job_preview.ts",  # R4-03 — 확인 면(생성 값 미리보기) React producer
        "src/screens/job_read.ts",  # R4-01 — job read surface controller/producer
        "src/screens/job_relink.ts",  # R4-03 — 저수준 재연결 port 의 React 구현
        "src/screens/job_result.ts",  # R4-03 — 결과 3태 구획·실행 기록 React producer
        "src/screens/job_run.ts",  # R4-03 — 실행 표면 React controller/producer
        "src/screens/job_run_state.ts",  # R4-03 — 실행 정체(세대·지문·토큰) reducer
        "src/screens/library.ts",  # R4-01 — 문서 작업 React surface
        "src/screens/path_actions.ts",  # R4-01 — 경로 열기 React action
        "src/screens/ports.ts",  # R4-01 — 화면 경계 typed ports
        "src/screens/product_screen_executor.ts",  # R4-04 — 동기 visibility/focus/scroll 집행
        "src/screens/product_screens.ts",  # R4-04 — 네 화면 mounted-hidden 합성
        "src/screens/runtime.ts",  # R4-01 — raw snapshot fanout/runtime model
        "src/screens/screen_lifecycle_registry.ts",  # R4-04 — editor/workbench 이탈 owner
        "src/screens/segment_view.ts",  # R4-02 — 채움 표지 세그먼트 React 후계
        "src/screens/sheet_picker.ts",  # R4-02 — 시트 확정 게이트 React 구현
        "src/screens/workbench.ts",  # R4-02 — 작업대 React controller/producer
            "src/screens/workbench_state.ts",  # R4-02 — 작업대 draft 투영
            "src/shell/app.ts",  # R5-01 — React 셸 adapter·listener attachment 서술
            "src/shell/host.ts",  # R3-02 — React ShellHost: 셸 리스너·부팅 시퀀스 수명주기
            "src/shell/nav.ts",  # R3-02 — 셸 상태기계(라우팅·ready·재당김 규약·닫기 직렬화 판정)
            "src/shell/preferences.ts",  # R5-01 — theme·personalization React 셸 서비스
        "src/state/store.ts",  # R2-03 — 전송-충실 스냅샷 store(값 해석 0)
    ], f"`.ts` 서브트리 전수가 어긋납니다: {ts_members}"
    assert len(sources) >= 40, (
        f"프런트 소스를 {len(sources)}장만 읽었습니다 — 수집이 헛돕니다."
    )


def test_selftest_api_global_has_exactly_one_producer() -> None:
    """``__hwpxTest`` 생산자는 정확히 하나이고 ``defineProperty`` 로만 선다(#372 D-07).

    별칭 게이트(:func:`test_temporary_aliases_have_exactly_one_central_producer`)는
    ``^window.X =`` 를 세므로 ``defineProperty`` 로 만든 이 전역을 **보지 못한다**. 그 공백을
    이 게이트가 메운다 — 없으면 이 저장소의 유일한 "생산자 계측이 없는 전역"이 된다.

    대입(``window.__hwpxTest =``)을 금지하는 이유는 재대입·재정의 가능성이다: 쓰기 가능한
    전역이면 페이지 스크립트가 능력을 갈아끼울 수 있고, 그러면 "호스트가 인증한 통로"라는
    성질이 사라진다.
    """
    sources = _frontend_sources()

    assignments = {
        name for name, text in sources.items()
        if re.search(rf"(?:window|globalThis)\.{SELFTEST_API_GLOBAL}\s*=", strip_comments(text))
    }
    assert assignments == set(), (
        f"{SELFTEST_API_GLOBAL} 을 대입으로 만드는 자리가 있습니다: {sorted(assignments)} — "
        "쓰기 가능한 전역은 페이지가 갈아끼울 수 있습니다."
    )

    producers = {
        name for name, text in sources.items()
        if re.search(
            rf"defineProperty\([^,]+,\s*(?:SELFTEST_GLOBAL|[\"']{SELFTEST_API_GLOBAL}[\"'])",
            strip_comments(text),
        )
    }
    assert producers == {SELFTEST_API_PRODUCER}, (
        f"{SELFTEST_API_GLOBAL} 생산자가 {sorted(producers)} 입니다 — "
        f"{SELFTEST_API_PRODUCER} 하나여야 합니다."
    )

    #: 세 계정은 서로 섞이지 않는다.
    assert SELFTEST_API_GLOBAL not in EXPECTED_RUNTIME_GLOBALS
    assert SELFTEST_API_GLOBAL != PRODUCT_API_GLOBAL


#: 페이지 쪽에서 만들 수 있는 활성화 조건 — 시험 능력의 켜짐 경로가 되면 안 된다(#381).
_PAGE_CONTROLLED_CONDITIONS = (
    "location.search", "location.hash", "URLSearchParams", "document.cookie",
)

#: 빌드타임 분기 — 하나라도 있으면 "검사한 것"과 "출하한 것"이 갈릴 수 있다(D-07).
_BUILD_TIME_BRANCHES = ("import.meta.env", "process.env", "__DEV__", "NODE_ENV")


def _page_condition_offenders(sources: "dict[str, str]") -> "set[str]":
    """페이지-제어 조건을 읽는 자리 — 공유 수집 집합 위의 순수 술어."""
    return {
        f"{name}:{needle}"
        for name, text in sources.items()
        for needle in _PAGE_CONTROLLED_CONDITIONS
        if needle in strip_js_comments(text)
    }


def _build_branch_offenders(sources: "dict[str, str]") -> "set[str]":
    """빌드타임 분기가 있는 자리 — 공유 수집 집합 위의 순수 술어."""
    return {
        f"{name}:{needle}"
        for name, text in sources.items()
        for needle in _BUILD_TIME_BRANCHES
        if needle in strip_js_comments(text)
    }


def _bare_specifier_offenders(sources: "dict[str, str]") -> "list[str]":
    """bare specifier 위반 전수 — ``.js`` 는 전부, ``.ts`` 는 핀 유도 허용 목록 밖만.

    도달 그래프 순회와 달리 **파일 전수**를 평면으로 걷는다: 그래프에 아직 붙지 않은
    파일도 위반을 품은 채 앉아 있을 수 없고, 술어가 순수해 합성 표본으로 판별력을 잴 수
    있다(프로브 생존 검사). 도달성·순환은 그래프 순회 게이트가 따로 진다.
    """
    return [
        f"{name} -> {spec}"
        for name, text in sorted(sources.items())
        for spec in module_imports(strip_js_comments(text))
        if not spec.startswith(".")
        and not spec.endswith(".css")
        and not (name.endswith(".ts") and _ts_bare_allowed(spec))
    ]


def _reserved_global_producers(sources: "dict[str, str]") -> "set[tuple[str, str]]":
    """``__hwpx`` 계열 예약 전역의 생산자 전수 — 대입이든 ``defineProperty`` 든.

    별칭 게이트는 은퇴 목록 27 이름만, selftest 생산자 게이트는 ``__hwpxTest`` 만 겨눈다.
    그 사이에 「`.ts` 가 같은 예약 이름을 재대입한다」와 「새 ``__hwpx*`` 이름을 만든다」가
    사각으로 남는다 — 정적 층의 이 한 줄이 그 자리를 메우고, 런타임 후계는 live 왕복이
    진다(rev3 착수 반영 ①).
    """
    producers: "set[tuple[str, str]]" = set()
    for name, text in sources.items():
        code = strip_js_comments(text)
        for alias in re.findall(
            r"(?m)(?:window|globalThis)\.(__hwpx[A-Za-z0-9_$]*)\s*=(?!=)", code
        ):
            producers.add((name, alias))
        for match in re.findall(
            r"defineProperty\([^,]+,\s*(?:SELFTEST_GLOBAL|[\"'](__hwpx[A-Za-z0-9_$]*)[\"'])",
            code,
        ):
            producers.add((name, match or "__hwpxTest"))
    return producers


def test_selftest_activation_reads_no_page_controllable_condition() -> None:
    """URL 쿼리·해시·쿠키로 시험 능력을 켤 수 없다(#381 불변식).

    쿼리스트링·``location.hash``·쿠키는 전부 **페이지 쪽에서 만들 수 있는** 조건이다. 하나라도
    활성화 경로가 되면 "호스트가 이 창을 시험용으로 띄웠다"를 증명하지 못한다. 그래서 프런트
    전체(`.js`+`.ts` 공유 수집 집합)에서 그 판독이 **0**이어야 한다.

    이것은 정적 절반이다("선언은 살고 결과는 죽는다") — 실제 창에서의 비노출은
    ``tests/test_web_selftest_gate.py`` 의 실런타임 음성이 진다.
    """
    offenders = _page_condition_offenders(_frontend_sources())

    assert offenders == set(), (
        f"페이지가 만들 수 있는 조건을 읽는 자리가 있습니다: {sorted(offenders)}"
    )


def test_reserved_global_family_has_exactly_the_two_known_producers() -> None:
    """예약 이름(``__hwpx`` 계열)의 생산자는 정확히 둘 — 합성 루트와 selftest api 뿐이다."""
    producers = _reserved_global_producers(_frontend_sources())

    assert producers == {
        ("src/bootstrap.js", PRODUCT_API_GLOBAL),
        ("src/selftest/api.js", SELFTEST_API_GLOBAL),
    }, f"예약 전역 생산자 전수가 어긋납니다: {sorted(producers)}"


def test_reserved_global_contract_is_single_sourced() -> None:
    """예약 전역의 이름·접촉 allowlist 는 계약 파일 하나가 정본이다(#490 F1).

    판독 술어(node AST 게이트 ``tests/js/pywebview_allowlist.test.js``)와 생산 술어(위
    producer 전수)가 **같은 파일**을 읽어야 「pywebview 를 막을 때 ``__hwpx`` 를 안
    넓힌다」 결함류가 형식으로 죽는다. 여기서는 그 결선을 고정한다 — 이름 전수가 제품
    전역 상수와 일치하고, allowlist 의 파일이 전부 실재하며(등재가 실물을 앞지르는
    방향은 node 쪽 양방향 대조가 막는다), 가족 술어의 접두가 이름 전수를 덮는다.
    """
    contract = STATIC_CLOSURE_CONTRACT["reserved_globals"]

    assert set(contract) == {"pywebview", PRODUCT_API_GLOBAL, SELFTEST_API_GLOBAL}, (
        f"계약의 예약 전역 이름 전수가 어긋납니다: {sorted(contract)}"
    )
    for name, files in contract.items():
        for rel in files:
            assert (SOURCE_ROOT / rel).is_file(), (
                f"{name} allowlist 의 {rel} 이 저장소에 없습니다 — 등재가 실물을 앞섰습니다"
            )
    assert all(name == "pywebview" or name.startswith("__hwpx") for name in contract), (
        "가족 술어(pywebview 정확 일치 + __hwpx 접두)가 계약 이름을 못 덮습니다 — "
        "새 전역은 술어와 계약을 한 변경으로 넓혀야 합니다"
    )


def test_bare_specifiers_are_closed_over_the_whole_source_set() -> None:
    """bare specifier 폐포 — ``.js`` 는 0, ``.ts`` 는 핀 유도 허용 목록 안뿐이다."""
    offenders = _bare_specifier_offenders(_frontend_sources())

    assert offenders == [], f"허용 밖 bare specifier 가 있습니다: {offenders}"


def test_the_react_subtree_holds_no_edge_into_the_legacy_graph() -> None:
    """Vanilla fallback 부재의 정적 절반 — `.ts` 서브트리에서 legacy 로 가는 간선이 0 이다.

    fallback 은 코드 경로가 있어야 성립한다. React 모듈이 legacy 트리(``frontend/js/**``)를
    import 하지도, legacy 화면 루트를 DOM 으로 붙들지도 않으면 「React 실패 시 Vanilla 복귀」
    는 구조적으로 불가능하다(#405 불변식 — 부팅 실패를 폴백으로 숨기지 않는다). 실패의
    착지는 경보 경로 하나이고, 그 경로의 실거동은 node 게이트(react_root.test.js)가 진다.
    """
    ts_sources = {
        name: strip_js_comments(text)
        for name, text in _frontend_sources().items()
        if name.endswith(".ts")
    }
    assert ts_sources, "`.ts` 서브트리를 한 장도 못 읽었습니다 — 아래 0건이 공허합니다."

    legacy_imports = {
        f"{name} -> {spec}"
        for name, text in ts_sources.items()
        for spec in module_imports(text)
        if spec.startswith(".") and "/js/" in spec
    }
    assert legacy_imports == set(), (
        f"React 서브트리가 legacy 모듈을 import 합니다: {sorted(legacy_imports)}"
    )

    legacy_surfaces = {
        f"{name}:{needle}"
        for name, text in ts_sources.items()
        #: R4-04 뒤 화면 root/overlayRoot는 ProductScreens가 직접 소유·portal한다. 여기서는
        #: successor 없는 migration host 셋이 React 그래프에 되살아나는지만 센다.
        for needle in ("jobStatusHost", "jobDataHeaderReactHost", "jobDataBodyReactHost")
        if needle in text
    }
    assert legacy_surfaces == set(), (
        f"React 서브트리가 legacy 화면 루트를 붙듭니다: {sorted(legacy_surfaces)}"
    )


def test_the_extended_scan_predicates_bite_a_synthetic_ts_probe() -> None:
    """프로브 생존 — 합성 ``.ts`` 표본에 각 술어가 실제로 문다(rev3 §4.2-1·§7).

    확장이 선언으로만 살고 결과가 죽는 모양(스캔은 넓혔는데 술어가 안 무는 상태)을 여기서
    막는다. 표본은 실파일이 아니라 값이다 — 다음 사람의 작업트리를 위협하지 않는다.
    """
    probe = {
        "src/react/zz_probe.ts": (
            'import "left-pad";\n'
            'import { createRoot } from "react-dom/client";\n'
            "const q = location.search;\n"
            "const env = import.meta.env;\n"
            "void bootProduct();\n"
            'window.__hwpx = {};\n'
            'Object.defineProperty(window, "__hwpxProbe", { value: 1 });\n'
        ),
    }

    assert _bare_specifier_offenders(probe) == ["src/react/zz_probe.ts -> left-pad"], (
        "핀 유도 허용 목록이 미선언 지정자를 놓치거나 선언 의존을 물었습니다."
    )
    assert _page_condition_offenders(probe) == {"src/react/zz_probe.ts:location.search"}
    assert _build_branch_offenders(probe) == {"src/react/zz_probe.ts:import.meta.env"}
    assert _reserved_global_producers(probe) == {
        ("src/react/zz_probe.ts", "__hwpx"),
        ("src/react/zz_probe.ts", "__hwpxProbe"),
    }
    #: 합성 루트 참조 핀도 같은 표본을 문다 — `.ts` 의 두 번째 실행 경로 차단이 실재한다.
    assert len(
        re.findall(rf"\b{re.escape(BOOTSTRAP_EXPORT)}\b",
                   strip_js_comments(probe["src/react/zz_probe.ts"]))
    ) == 1


def _invocation_census(sources: "dict[str, str]", callee: str) -> "dict[str, int]":
    """이름 하나의 **날 호출** 지점 census — 정의·멤버-접근은 세지 않는다(R2-04 · #408).

    두 제외가 각각 오늘의 거짓 빨강을 막는다: ``function NAME(`` 정의(boot.ts:40 ·
    store.ts:69)와 ``deps.createRoot(target)`` 류 멤버-접근 호출(root.ts:56 — 주입받은
    factory 의 사용이지 새 결속이 아니다). 판별력은 합성 표본 게이트가 잰다.
    """
    pattern = re.compile(rf"(?<![.\w$])(?<!function ){re.escape(callee)}\(")
    census = {
        name: len(pattern.findall(strip_js_comments(text)))
        for name, text in sources.items()
    }
    return {name: count for name, count in census.items() if count > 0}


def test_react_root_and_store_are_single_sited() -> None:
    """다중 root 의 정적 음성(R2-04 · #408) — 결속과 착좌가 각각 정확히 한 자리다.

    커밋-키 가드(root.ts)는 **같은 컨테이너**의 재마운트만 막고, 마운트 마커는 root.ts
    경로만 심는다 — 다른 컨테이너에 둘째 root 를 세우는 파일은 런타임 가드도 실창 마커
    census 도 보지 못한다. R2-00 불변식(「다중 island 를 최종 구조로 만들지 않는다」)의
    유일한 방어가 이 정적 층이다.
    """
    sources = _frontend_sources()

    #: ① react-dom 결속은 `boot.ts` 하나 — bare 허용(`_ts_bare_allowed`)이 `.ts` 전역이라
    #: 둘째 파일의 `react-dom/client` import 는 이 핀 없이는 어느 게이트에도 안 걸린다.
    binders = {
        name for name, text in sorted(sources.items())
        if any(
            spec == "react-dom" or spec.startswith("react-dom/")
            for spec in module_imports(strip_js_comments(text))
        )
    }
    assert binders == {
        "src/react/boot.ts",
        "src/screens/product_screen_executor.ts",
        "src/screens/product_screens.ts",
    }, (
        f"react-dom 에 결속한 파일이 {sorted(binders)} 입니다 — 둘째 결속은 둘째 root 의"
        " 자리입니다. ProductScreens는 createPortal, executor는 flushSync만 소유합니다."
    )
    product_source = strip_js_comments(sources["src/screens/product_screens.ts"])
    executor_source = strip_js_comments(sources["src/screens/product_screen_executor.ts"])
    assert "createPortal" in product_source and not re.search(r"\bcreateRoot\s*\(", product_source)
    assert "flushSync" in executor_source and not re.search(r"\bcreateRoot\s*\(", executor_source)

    #: ①-보강(#489 Codex P2): 결속의 **형태**도 잠근다 — named import 만. 이름공간(`* as`)·
    #: 기본 결속이 허용 파일 안에 서면 `NS.createRoot(…)` 멤버-접근 호출이 census 의
    #: 멤버-접근 제외를 정확히 타고 우회한다. 형태를 잠그면 「react-dom 에 결속된
    #: 멤버-접근」이 존재할 수 없어, 그 제외(root.ts 주입 소비의 거짓 빨강 방어)가 안전하다.
    for name, text in sorted(sources.items()):
        for clause in re.findall(
            r"import\s+([^;]*?)\s+from\s*[\"']react-dom(?:/[^\"']*)?[\"']",
            strip_js_comments(text),
        ):
            assert re.fullmatch(r"(?:type\s+)?\{[^}]*\}", clause.strip()), (
                f"{name} 의 react-dom import 가 named 형태가 아닙니다: {clause!r} — "
                "이름공간·기본 결속은 멤버-접근 호출로 census 를 우회합니다."
            )

    #: ② 날 `createRoot(` 호출은 boot.ts 의 주입 클로저 한 곳 — root.ts 의 멤버-접근
    #: 사용(deps.createRoot)은 결속이 아니라 주입의 소비라 세지 않는다.
    assert _invocation_census(sources, "createRoot") == {"src/react/boot.ts": 1}

    #: ③ 합성 루트 factory 착좌 census — 각각 bootstrap.js 정확 1회.
    assert _invocation_census(sources, "bootReactRoot") == {"src/bootstrap.js": 1}
    assert _invocation_census(sources, "createSnapshotStore") == {"src/bootstrap.js": 1}


def test_the_multi_root_census_bites_synthetic_probes() -> None:
    """census 술어의 판별력 — 겨눈 것은 물고, 제외한 것은 물지 않는다.

    음성 대조의 절반은 「안 무는 쪽」이다: 정의·멤버-접근을 세면 오늘 당장 거짓 빨강이라
    (boot.ts:40 정의 · root.ts:56 멤버-접근), 무는 쪽만 확인한 술어는 내일 그 둘을 세는
    회귀를 못 막는다.
    """
    #: 무는 쪽 — 둘째 결속·둘째 날 호출.
    island = {
        "src/react/zz_island.ts": (
            'import { createRoot } from "react-dom/client";\n'
            "export function seatSecondIsland(host: Element): void {\n"
            "  createRoot(host);\n"
            "}\n"
        ),
    }
    assert _invocation_census(island, "createRoot") == {"src/react/zz_island.ts": 1}
    assert any(
        spec.startswith("react-dom")
        for spec in module_imports(strip_js_comments(island["src/react/zz_island.ts"]))
    )

    #: 무는 쪽 2(#489 Codex P2) — 이름공간 결속의 멤버-접근 호출. census 는 이것을 **못
    #: 본다**(멤버-접근 제외) — 그 사실의 확인이, 형태 핀이 의무인 이유의 실증이다.
    namespaced = {
        "src/react/zz_ns.ts": (
            'import * as ReactDOM from "react-dom/client";\n'
            "export function seat(host: Element): void {\n"
            "  ReactDOM.createRoot(host);\n"
            "}\n"
        ),
    }
    assert _invocation_census(namespaced, "createRoot") == {}
    clauses = re.findall(
        r"import\s+([^;]*?)\s+from\s*[\"']react-dom(?:/[^\"']*)?[\"']",
        strip_js_comments(namespaced["src/react/zz_ns.ts"]),
    )
    assert clauses == ["* as ReactDOM"]
    assert re.fullmatch(r"(?:type\s+)?\{[^}]*\}", clauses[0].strip()) is None, (
        "형태 핀이 이름공간 결속을 통과시키면 census 우회가 열립니다."
    )

    #: 안 무는 쪽 — 정의와 멤버-접근 위장.
    disguised = {
        "src/react/zz_disguise.ts": (
            "export function bootReactRoot(host: unknown): void {\n"
            "  void host;\n"
            "}\n"
            "const deps = { createRoot: (target: Element): void => { void target; } };\n"
            "export function seat(target: Element): void {\n"
            "  deps.createRoot(target);\n"
            "}\n"
        ),
    }
    assert _invocation_census(disguised, "bootReactRoot") == {}
    assert _invocation_census(disguised, "createRoot") == {}


def test_one_build_entry_and_no_build_time_branch() -> None:
    """산출물은 **한 번의 빌드 하나**다 — 테스트 전용 번들·빌드타임 분기가 없다(D-07).

    정상 실행과 시험 실행이 같은 바이트를 쓰려면 갈림이 **런타임 호스트 능력** 하나여야 한다.
    빌드타임 분기(``import.meta.env`` 등)가 하나라도 있으면 "검사한 것"과 "출하한 것"이 갈릴
    수 있고, 그 갈림은 산출물 해시가 같아도 보이지 않는다.
    """
    config = (ROOT / "vite.config.mjs").read_text(encoding="utf-8")

    for forbidden in ("input:", "rollupOptions", "build.lib", "lib:"):
        assert forbidden not in config, (
            f"Vite 설정에 {forbidden} 가 있습니다 — 두 번째 entry/번들의 자리입니다."
        )

    scripts = re.findall(r"<script\b[^>]*\bsrc=\"[^\"]+\"[^>]*></script>",
                         SOURCE_INDEX.read_text(encoding="utf-8"))
    assert scripts == ['<script type="module" src="./src/main.js"></script>']

    offenders = _build_branch_offenders(_frontend_sources())
    assert offenders == set(), (
        f"빌드타임 분기가 있습니다: {sorted(offenders)} — 시험용 산출물이 갈릴 수 있습니다."
    )


def test_whole_frontend_graph_from_the_entry_has_no_cycles_and_no_bare_specifiers() -> None:
    """entry 에서 **실제로 도달하는 전 그래프**에 순환도 외부 지정자도 없다.

    :func:`test_esm_module_graph_has_no_cycles` 는 ``frontend/js/`` 25개와 compat 의
    ``../js/`` 간선만 본다. N-09 가 selftest 모듈 아홉을 제품 그래프에 **실제로 붙였으므로**
    (같은 번들 하나가 계약이다 — D-07) 그 부분은 옛 게이트의 사각이었다. 여기서 entry 부터
    상대 import 를 전부 따라가 사각을 없앤다.

    bare 지정자(``vite``·``lodash`` 같은 외부 패키지)도 0이어야 한다 — 하나라도 생기면
    배포본이 node_modules 를 필요로 하게 되고, 그것은 오프라인 부팅 계약(D-04)의 파산이다.
    """
    from posixpath import dirname, join, normpath

    entry = SOURCE_ENTRY.relative_to(SOURCE_ROOT).as_posix()
    seen: dict[str, int] = {}
    bare: list[str] = []
    visited: set[str] = set()

    def visit(node: str, trail: tuple[str, ...]) -> None:
        if seen.get(node) == 1:
            raise AssertionError(f"import 순환: {' -> '.join((*trail, node))}")
        if seen.get(node) == 2:
            return
        seen[node] = 1
        visited.add(node)
        path = SOURCE_ROOT / node
        #: 간선 방문만 하고 내부를 안 읽으면 그 서브트리는 게이트의 사각에서 자란다
        #: (L16 B1 — rev1 은 「충돌」로 반대로 적었던 자리다). 하강도 확장자 열거가 아니라
        #: **전부**다(#490 리뷰 P2): `.ts` 열거로 두면 미래의 정당한 `.tsx`/`.mts` 가 등재
        #: 뒤에도 자기 간선을 영영 안 읽혀, 그 안의 순환·bare 가 조용히 통과한다. 상대
        #: import 가 가리키는 노드는 정의상 코드 모듈이라 무조건 읽는다.
        if path.is_file():
            for spec in module_imports(path.read_text(encoding="utf-8")):
                if spec.startswith("."):
                    visit(normpath(join(dirname(node), spec)), (*trail, node))
                elif spec.startswith("../css/") or spec.endswith(".css"):
                    continue
                elif path.suffix != ".js" and _ts_bare_allowed(spec):
                    #: 빌드가 해소하는 **핀된** 의존 — TS-가족(¬`.js` — 등재 필터와 같은
                    #: 감산형)에만 열린 문이다. `.js` 는 여전히 bare 0 이라 비 React JS가
                    #: React 를 직접 싣는 경로가 없다.
                    continue
                else:
                    bare.append(f"{node} -> {spec}")
        seen[node] = 2

    visit(entry, ())

    assert bare == [], f"외부 지정자가 있습니다: {bare}"

    #: React root 모듈 셋이 **실제로** 제품 그래프에 붙어 있다 — 배선이 끊겨도 "순환 0"은
    #: 여전히 초록이므로, selftest 와 같은 논거로 도달 사실을 따로 단언한다(R2-01).
    reached_react = sorted(n for n in visited if n.startswith("src/react/"))
    assert reached_react == [
        "src/react/boot.ts",
        "src/react/boundary.ts",
        "src/react/root.ts",
    ], f"React root 모듈이 제품 그래프에 닿지 않습니다: {reached_react}"

    #: selftest 모듈이 **실제로** 그래프에 붙어 있다 — N-08 의 inert 상태가 끝났다는 실행 증거.
    #: 이 단언이 없으면 배선이 끊겨도 "순환 0"은 여전히 초록이다.
    reached_selftest = sorted(n for n in visited if n.startswith("src/selftest/"))
    assert reached_selftest, "selftest 모듈이 제품 그래프에 닿지 않습니다 — 능력이 설 수 없습니다."
    assert "src/selftest/api.js" in reached_selftest
    assert "src/selftest/boot.js" in reached_selftest
    assert "src/selftest/runner.js" in reached_selftest
    assert "src/selftest/probes/index.js" in reached_selftest
