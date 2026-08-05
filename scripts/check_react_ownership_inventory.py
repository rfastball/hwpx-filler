"""React 소유권 인벤토리 원장(``docs/react_ownership_inventory.toml``)의 재실측기.

## 무엇을 지키는가

R1 의 완료물은 「React 소유 단위와 검증 책임의 **미분류 0** 원장」이다. 그 「0」을 선언으로
적으면 병합 다음 날부터 조용히 거짓이 된다 — 노드가 늘어도 원장은 초록이기 때문이다.
그래서 이 스크립트는 **선언을 읽지 않고 저장소를 다시 잰다**. 네 방향으로 센다:

* ``M − C`` — 저장소에 있는데 원장에 없는 노드(**미분류**)
* ``C − M`` — 원장에 있는데 저장소에서 사라진 노드(**유령 행**)
* ``members_expected`` — 접힌 컨테이너 행의 실제 배정 수(접기가 성장을 삼키지 못하게)
* ``blind_spot`` — 술어가 **못 보는 것**의 오늘 크기(사각이 자라면 붉는다)

넷째가 이 원장의 뼈대다. 이 저장소에서 계측 술어가 네 번 틀렸고, 그중 하나는 「정규식이
틀렸다」가 아니라 **「술어의 커버리지를 안 물었다」**였다(2칸 들여쓰기 관례가 0칸 최상위 4를
못 보고 비-export 함수 지역 12를 상태로 오독). 값만 지키는 계약은 그 결함류를 못 막는다.

## 형식 계약

* **TOML 만 읽는다.** 마크다운을 파싱하는 추출기는 만들지 않는다(`R1-ARTIFACT-LAYOUT:v2` §3).
  1차 구현 라운드가 695행 마크다운 파서로 무너진 자리다.
* **모든 계측 항목은 ``predicate``·``scope``·``unit`` 셋을 든다.** 하나라도 없으면 값이 아니라
  구조 오류다 — 같은 이름이 다른 것을 가리키는 사고(`innerHTML` 61/71/83/50)가 이 계약의 이유다.
* **``evidence`` 는 ``{file, line, anchor}``.** 파일 존재와 행수만 보면 824행 문서의 아무 줄이나
  초록이다. 앵커 문자열을 그 줄에서 실제로 읽는다 — 집필 중 남의 커밋이 상수를 15줄 밀었을 때
  앵커 없는 증거였다면 초록이었다.
* **분류 어휘는 소문자 5종.** 이 저장소의 기계 판독 TOML 은 enum 값에 대문자를 쓰지 않는다.

## 자족 판정

R1-99 감사자는 write 0 · 네트워크 0 · 실행 1회로 판정한다::

    uv run python scripts/check_react_ownership_inventory.py --report json

종료 코드가 판정이고, JSON 은 축별 ``measured/covered/unclassified/ghost/duplicate``,
``members_mismatch``, ``blind_spot_delta``, 계측 불일치, ``unknown`` 개수를 든다.

## 이 파일이 순수 함수를 노출하는 이유

:func:`check` 는 **파싱된 문서와 저장소 루트를 인자로** 받는다. 그래서 음성 대조가 파일 텍스트
전역 치환 없이 **한 좌표만** 바꿀 수 있다 — 전역 치환으로 음성 대조가 스스로를 가린 전례가
이 저장소에 있다.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT = REPO_ROOT / "docs" / "react_ownership_inventory.toml"
NODE_EXTRACTOR_SCRIPT = "scripts/extract_js_ast_axes.mjs"

#: 분류 어휘 — `R1-ARTIFACT-LAYOUT:v2` §2 가 정본이고 중앙 V1 이 소문자로 못박았다.
#: `classification` 과 구 `p_authority` 는 값 공간이 같은 한 축이라 중앙 V7 이 열을 합쳤다.
CLASSIFICATIONS = frozenset(
    {"react", "python_product", "host", "retire", "p_review_required"}
)
NODE_KINDS = frozenset({"dom", "state", "subscription", "lifecycle"})
BACKINGS = frozenset({"parser", "ast", "regex-convention", "python-ast", "python-glob"})
#: ``per-line`` 은 줄 단위로 돌린 **일치 수**, ``per-occurrence`` 는 파일 전체에 돌린 일치 수,
#: ``per-matching-line`` 은 **일치가 있는 줄 수**다. 셋을 가르는 이유가 원장에 실측으로 있다 —
#: 같은 술어 ``window\.pywebview`` 가 32(줄) 와 34(회) 를 낸다.
GRANULARITIES = frozenset({"per-line", "per-occurrence", "per-matching-line"})
P_HANDOFF_VALUES = frozenset({"yes", "no"})

#: G15 「인계 항목 증거 연결 누락 0」의 기계 판독 형태. 공란은 실패이고 「모름」은 공란이
#: 아니라 ``unknown`` 명시값이다 — 게이트가 그 수를 **보고**해 R1-99 가 판정한다.
P_REVIEW_FIELDS = ("producer", "consumer", "call_path", "contract", "test")

#: 이관 슬라이스 어휘 — R2~R5 구현 슬라이스 이슈. `SCREEN-SPLIT-ROADMAP:v1` 의 책임 축이
#: R4-01~R4-03 에 정렬한다. 새 Vanilla 파일 목록을 만들지 않는다(L15).
HANDOFF_SLICES = frozenset(
    {
        "R2-01 #405", "R2-02 #406", "R2-03 #407", "R2-04 #408",
        "R3-01 #410", "R3-02 #411", "R3-03 #412",
        "R4-01 #414", "R4-02 #415", "R4-03 #416", "R4-04 #417",
        "R5-01 #419", "R5-02 #420", "R5-03 #421",
    }
)


#: **분모의 정의역도 원장 밖이다.** 하한만으로는 부족했다 — 축의 `scope`·`scope_excluded` 가
#: 원장 안에 있으면 scope 를 좁히고 그만큼 행을 정리하는 것으로 **측정 집합 M 자체가** 줄고,
#: 폐포(`M−C`)는 계속 참이라 조용하다. 그래서 게이트가 **제품 트리를 스스로 열거**하고
#: 「모든 파일이 어떤 축의 scope 또는 명시 제외에 덮이는가」를 1차 방벽으로 세운다.
PRODUCT_TREE_GLOBS = (
    "frontend/**/*.js",
    "frontend/**/*.mjs",
    "frontend/**/*.html",
    "frontend/**/*.css",
)

#: 재고정은 계약이다 — 기준선을 옮기는 것은 값 하나를 고치는 일이 아니라 중앙 판정이 붙는
#: 사건이다. 40자리 hex 모양만 보면 `"0"*40` 도 통과하므로 좌표 자체를 든다.
#: 재고정 v5 = R3-03(#412) parity 검증 — base 는 rev4 packet 이 고정한 `15d3444`.
EXPECTED_BASELINE_SHA = "15d3444a256057f95b6ea6fcedd31b562a03f28d"

#: **분모는 원장이 아니라 여기가 든다.** 원장에서 유도하면 축을 지우거나 scope 를 좁히고 그만큼
#: 행을 정리하는 것으로 초록이 되고, 극단에는 **빈 원장이 통과**한다 — 「선언은 살고 결과는
#: 죽는다」의 정확한 형태다. 여기 값은 **정확값이 아니라 하한**이라 정상 성장은 안 막고 붕괴만
#: 잡는다. **하한을 낮추는 변경은 그 자체가 리뷰 대상**이고 사유를 주석으로 남긴다.
#: 축별 하한은 **2차 백스톱**이다. 하한에는 슬랙이 있고 그 슬랙이 축마다 무음 삭감 예산이 되므로
#: 1차 방벽은 전수 피복과 :data:`AXIS_DIGESTS` 다. 하한을 낮추는 변경은 사유와 함께여야 하고
#: 테스트의 `EXPECTED_AXIS_CONTRACT` 도 함께 고쳐야 한다.
AXIS_FLOORS: dict[str, int] = {
    "dom_static": 200,              # 오늘 232
    "dom_data_attr": 8,             # 오늘 9
    "dom_js_data_attr": 80,         # 오늘 86 — JS/TS 생산자 이름×파일
    "dom_js_site": 22,              # 오늘 26
    "state_js_module": 44,          # 오늘 50
    "state_snapshot_channel": 6,    # 오늘 6 — 화면이 줄면 그 자체가 계약 변경이라 여유를 안 둔다
    "state_ring1": 10,              # 오늘 11
    # R3-01(#410)이 문서 리스너 소유를 이양하며 두 축이 줄었다: popover 모듈-평가 부착 8 +
    # undo_toast 1 + modal.js 부착 5/해제 5 가 엔진 배선·React host(`.ts` — 이 축의 scope 밖,
    # READY 기록의 #490 인접 사각)로 옮겨 갔다. 하한 인하는 그 실측을 따른다 — 더 줄면
    # 그때 또 사유가 필요하다(조용한 삭감 금지).
    # R3-02(#411)가 셸 리스너 7(백스톱·탭 2접점 아닌 nav 위임 1·도구 2·라벨 동기 2·부팅 훅)을
    # app.js 서술 + React ShellHost 부착(src/shell/host.ts — 같은 `.ts` 사각, #491)으로
    # 이양했다. 부팅 훅 이양으로 lifecycle_hook 도 함께 줄었다(IMMERSIVE 목록은 상태기계
    # nav.ts 로). 인하는 실측 그대로다.
    "subscription_listener": 96,    # 오늘 98
    "subscription_release": 6,      # 오늘 7
    "subscription_push": 5,         # 오늘 6
    "lifecycle_factory": 16,        # 오늘 18
    "lifecycle_hook": 7,            # 오늘 8
}

#: 축의 **측정 계약** 해시 — 술어 · scope · scope_excluded · 사각/오검 프로브의 정규화 지문.
#: 원장이 술어를 좁히거나(M24) 축 제외를 넓히거나(M26) 프로브를 「없는 것」으로 만들면
#: 여기와 어긋난다. **원장은 값을, 게이트는 술어를** 든다.
#: 값은 `uv run python scripts/check_react_ownership_inventory.py --print-pins` 가 낸다.
AXIS_DIGESTS: dict[str, str] = {
    "dom_data_attr": "e0bd6cb1822fd50fefbda2c3fac621d5",
    "dom_js_data_attr": "34434413efa1aeb4dd7a9779ad680252",
    "dom_js_site": "21f6634bedf7f3777ec66d1b72991493",
    "dom_static": "a0de506720a9704065dde2bf17410d50",
    "lifecycle_factory": "cf3701bfb0908f4d0582200ce8273918",
    "lifecycle_hook": "05809936a7af41d071c9da1f786c0370",
    "state_js_module": "1633eccf8b783f1d712a5b9e158a6ed5",
    "state_ring1": "9742c77daae0c11112e40c009a5b23c6",
    "state_snapshot_channel": "5891957f0ed54565587e17c150eed087",
    "subscription_listener": "2fc5bdf7415bc281524144a514e9ee28",
    "subscription_push": "5201c1ab611d0f09a743bd1e6afced4a",
    "subscription_release": "b6ac96d2f30c9122a679e7c1c01643b1",
}

#: 계측·판정 요구 항목도 같은 이유로 게이트가 목록을 든다 — 항목을 지우는 것은 값이 아니라
#: **계약을 줄이는 것**이라 원장 혼자 결정할 수 없다.
EXPECTED_METRIC_IDS = frozenset({
    "innerhtml-assignment", "mutable-module-state", "push-subscription-sites",
    "listener-attach-sites", "listener-release-sites", "dom-stable-ids",
    "dom-data-attribute-kinds", "data-attribute-bearing-elements",
    "js-generated-id-sites", "screen-action-pairs",
    "window-pywebview-references", "pywebview-api-references", "export-function-declarations",
})
EXPECTED_REVIEW_ITEM_IDS = frozenset({
    "bridge/close-guard-state", "gate/architecture-bridge-one-way",
    "gate/screen-roots-partial", "gate/preserve-wrapped-files-partial",
    "doc/bridge-header-breakdown", "doc/screens-py-transport-comment",
})
#: 제품 트리보다 **좁은 scope** 를 든 축 → 그 한계의 소유자. scope 를 넓히는 것이 답이 아닌
#: 자리가 있다(오늘의 6은 「화면 파일 + data_picker.js 안의 푸시 구독」이 맞는 단위다). 그때는
#: 기계를 넓히지 말고 **주장을 정확히 좁힌다** — 다만 그 좁힘이 산문 각주면 늙으므로,
#: 게이트가 「이 축은 한계를 선언해야 한다」를 들고 그 선언의 소유자까지 대조한다.
NARROW_SCOPE_AXES: dict[str, str] = {
    "subscription_push": "R2-04 #408",
}

#: 제외 축 → 「크기 프로브를 요구하는가」. `size` 블록을 통째로 지우면 조용한 유예로
#: 되돌아가므로 **어느 제외가 크기를 드는지**도 게이트가 든다.
EXPECTED_EXCLUDED_AXES: dict[str, bool] = {
    "selftest_frontend_surface": True,
    "frontend_stylesheets": True,
}

#: 접기가 있어도 이만큼은 손으로 분류돼 있어야 한다. 노드 행을 0으로 만드는 것은 폐포를
#: 「측정 0 == 피복 0」으로 닫아 버리는 길이다.
NODE_ROW_FLOOR = 80

#: `repo_wide_metrics` 판정 — scope 의 첫 경로 조각이 리터럴이 아니면 저장소 전수로 본다.
_REPO_WIDE_HEAD = re.compile(r"[*?\[]")


class InventoryGateError(RuntimeError):
    """원장·저장소가 아니라 **게이트 자신의 전제**가 깨졌을 때만 던진다."""


# ──────────────────────────────────────────────────────────────────────────
# 저장소 컨텍스트 — 추출기가 공유하는 캐시
# ──────────────────────────────────────────────────────────────────────────


#: 이 확장자는 **텍스트여야 한다**. 디코드 실패를 `continue` 로 넘기면 정규식 축이 그 파일을
#: 조용히 안 보고, 같은 파일을 AST 축은 본다 — 「런타임 부재를 자동 감지해 조용히 스킵하지
#: 않는다」와 같은 축의 결함이라 구조 오류로 든다.
TEXT_SUFFIXES = frozenset({
    ".js", ".mjs", ".ts", ".tsx", ".py", ".html", ".css", ".toml", ".json", ".md",
})


def _read_text(path: Path) -> str | None:
    """텍스트로 읽는다. 바이너리(글꼴 등)는 ``None`` — 세지 않되 죽지도 않는다."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


class Repo:
    """저장소 한 그루에 대한 read-only 측정 컨텍스트."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[tuple[tuple[str, ...], tuple[str, ...]], list[Path]] = {}
        self._node_axes: dict[str, list[str]] | None = None
        self._html: _IndexParse | None = None
        #: 텍스트여야 하는데 UTF-8 로 못 읽은 파일 — 조용히 넘기지 않고 보고한다.
        self.decode_failures: set[str] = set()

    def files(self, scope: tuple[str, ...], excluded: tuple[str, ...] = ()) -> list[Path]:
        key = (scope, excluded)
        cached = self._files.get(key)
        if cached is None:
            blocked: set[Path] = set()
            for pattern in excluded:
                blocked.update(self.root.glob(pattern))
            seen: dict[Path, None] = {}
            for pattern in scope:
                for path in sorted(self.root.glob(pattern)):
                    if not path.is_file():
                        continue
                    if any(parent in blocked for parent in (path, *path.parents)):
                        continue
                    seen[path] = None
            cached = list(seen)
            self._files[key] = cached
        return cached

    def text(self, path: Path) -> str | None:
        """scope 안의 파일을 읽되 **텍스트여야 하는데 못 읽은 것**은 기록한다."""
        content = _read_text(path)
        if content is None and path.suffix.lower() in TEXT_SUFFIXES:
            self.decode_failures.add(self.relative(path))
        return content

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def html(self) -> _IndexParse:
        if self._html is None:
            self._html = _parse_index(self.root / "frontend" / "index.html")
        return self._html

    def node_axes(self) -> dict[str, list[str]]:
        """Node AST 추출기를 **한 번** 돌려 세 축을 받는다.

        Node 부재는 조용한 스킵이 아니라 실패다 — Node 는 이 저장소의 빌드 전제조건이고
        CI contract 잡은 pytest 앞에서 프런트 툴체인을 설치한다.
        """
        if self._node_axes is None:
            node = shutil.which("node")
            if node is None:
                raise InventoryGateError(
                    "Node 가 PATH 에 없습니다 — JS AST 축(id 사이트·모듈 상태)을 잴 수 없습니다. "
                    "Node 는 이 저장소의 빌드 전제조건이라 부재는 스킵 사유가 아닙니다."
                )
            script = REPO_ROOT / NODE_EXTRACTOR_SCRIPT
            if not script.is_file():
                raise InventoryGateError(f"AST 추출기가 없습니다: {script}")
            result = subprocess.run(
                [node, str(script), "--repo-root", str(self.root)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                raise InventoryGateError(
                    "AST 추출기가 실패했습니다.\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            self._node_axes = json.loads(result.stdout)
        return self._node_axes


# ──────────────────────────────────────────────────────────────────────────
# 파서 추출기 — `frontend/index.html`
# ──────────────────────────────────────────────────────────────────────────

_VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "source", "track", "wbr",
    }
)


@dataclass
class _IndexParse:
    ids: list[str] = field(default_factory=list)
    id_lines: dict[str, int] = field(default_factory=dict)
    #: id → 자기 자신을 **포함하지 않는** 조상 스택(문서 순서, 바깥→안쪽).
    ancestors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    data_attributes: Counter[str] = field(default_factory=Counter)
    #: `data-*` 를 든 요소의 (줄, id) — id 가 없는 것이 `dom_static` 232 **밖**이다.
    data_attr_elements: list[tuple[int, str | None]] = field(default_factory=list)
    unbalanced: int = 0
    #: 닫는 태그가 여는 태그와 **이름이 다른** 자리 — `(줄, 기대, 실제)`.
    #:
    #: 개수만 세면 `<div><span></div></span>` 처럼 **수는 맞고 순서가 틀린** 오정렬이
    #: 통과한다. 그때 브라우저의 관용 복구는 이 파서와 **다른 트리**를 만들 수 있고,
    #: 그러면 :attr:`ancestors` 가 거짓이 되어 접기(컨테이너 귀속)가 함께 거짓이 된다.
    mismatched: list[tuple[int, str, str]] = field(default_factory=list)


class _IndexCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out = _IndexParse()
        #: `(태그 이름, id)` — 이름을 함께 들어야 닫는 짝을 **대조**할 수 있다.
        self._stack: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = dict(attrs)
        element_id = mapping.get("id")
        if any(name.startswith("data-") for name in mapping):
            self.out.data_attr_elements.append((self.getpos()[0], element_id))
        if element_id:
            self.out.ids.append(element_id)
            self.out.id_lines[element_id] = self.getpos()[0]
            self.out.ancestors[element_id] = tuple(
                name for _tag, name in self._stack if name is not None
            )
        for name in mapping:
            if name.startswith("data-"):
                self.out.data_attributes[name] += 1
        if tag not in _VOID_ELEMENTS:
            self._stack.append((tag, element_id))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_ELEMENTS and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS:
            return
        if not self._stack:
            self.out.unbalanced += 1
            return
        opened, _element_id = self._stack.pop()
        if opened != tag:
            self.out.mismatched.append((self.getpos()[0], opened, tag))

    def close(self) -> None:  # noqa: D102 - HTMLParser API
        super().close()
        self.out.unbalanced += len(self._stack)


def _parse_index(path: Path) -> _IndexParse:
    if not path.is_file():
        raise InventoryGateError(f"정적 DOM 원본이 없습니다: {path}")
    parser = _IndexCollector()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.out


# ──────────────────────────────────────────────────────────────────────────
# 이름 붙은 추출기 레지스트리
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Extractor:
    """이름 붙은 추출기.

    ``scope`` 를 코드가 들고 원장의 ``scope`` 와 **일치를 강제**한다. 그래야 원장이 술어의
    범위를 혼자 다시 쓸 수 없다 — scope 부재·불일치가 이 저장소가 반복해 만난 결함류다.
    """

    backing: str
    scope: tuple[str, ...]
    run: Callable[[Repo], list[str]]
    scope_excluded: tuple[str, ...] = ()
    #: 여러 형태를 함께 세는 추출기는 **형태 이름 전수**를 든다. 원장이 같은 목록을
    #: `known_forms` 로 적고 게이트가 대조한다 — 「알려진 여섯 형태」라 적는 동안 추출기가
    #: 일곱을 세던 자리는 산문을 고쳐서는 다시 열린다.
    forms: tuple[str, ...] = ()


def _html_ids(repo: Repo) -> list[str]:
    return list(repo.html().ids)


def _html_data_attrs(repo: Repo) -> list[str]:
    return sorted(repo.html().data_attributes)


def _html_parse_anomalies(repo: Repo) -> list[str]:
    """파서의 관용 복구가 삼킬 수 있는 것 — 중복 id · 태그 불균형 · **오정렬**.

    오정렬(`<div><span></div></span>`)은 여닫는 **수가 맞아** 불균형 계수에 안 걸린다.
    그런데 브라우저의 복구는 이 파서와 다른 트리를 만들 수 있고, 그러면 조상 사슬이
    거짓이 되어 접기가 함께 거짓이 된다 — 개수가 아니라 **이름을 대조**해야 보인다.
    """
    parsed = repo.html()
    counts = Counter(parsed.ids)
    rows = [f"duplicate-id:{name}" for name, n in sorted(counts.items()) if n > 1]
    rows += [f"unbalanced-tag:{parsed.unbalanced}"] if parsed.unbalanced else []
    rows += [
        f"mismatched-close:{line}:{opened}/{closed}"
        for line, opened, closed in parsed.mismatched
    ]
    return rows


_NAIVE_DATA_ATTR = re.compile(r"data-[a-z-]+")


def _html_data_attr_regex_delta(repo: Repo) -> list[str]:
    """무앵커 정규식이 더 잡는 이름 — CSS 클래스·산문. 파서 쪽이 참값이다."""
    text = (repo.root / "frontend" / "index.html").read_text(encoding="utf-8")
    naive = set(_NAIVE_DATA_ATTR.findall(text))
    return sorted(naive - set(repo.html().data_attributes))


def _html_data_attr_elements(repo: Repo) -> list[str]:
    """`data-*` 를 든 **요소** 전수. `dom_data_attr.unit` 의 근거 문장을 데이터로 만든다."""
    return [f"frontend/index.html:{line}" for line, _ in repo.html().data_attr_elements]


def _html_data_attr_elements_without_id(repo: Repo) -> list[str]:
    """그중 id 가 없어 `dom_static` 232 밖인 것 — 이름 축이 유일한 계약면인 요소들."""
    return [
        f"frontend/index.html:{line}"
        for line, element_id in repo.html().data_attr_elements
        if not element_id
    ]


def _js_template_ids(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_template_ids"])


def _js_planted_data_attrs(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_planted_data_attrs"])


def _js_data_attr_dynamic(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_data_attr_dynamic"])


def _js_module_state(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_module_state"])


def _js_nonexported_fn_state(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_nonexported_fn_state"])


#: `dom_js_site` 의 앵커 정규식이 못 보는 네 형태. 오늘 전부 0이지만 **오늘 0인 것과 앞으로도
#: 0인 것은 다르다** — 그래서 프로브가 매번 그 0을 재확인한다.
#: 알려진 일곱 형태. **전수라고 주장하지 않는다** — 그것을 확인하는 프로브가 없다.
#:
#: 다섯째 이후는 마크업 문자열이 아니라 **DOM API** 로 id 를 심는 길이다. 셋 다 반증 라운드가
#: 찾아냈고, 특히 「줄바꿈된 `setAttribute("id", …)`」는 **선언한 형태를 프로브가 못 넘던**
#: 자리였다(줄 단위로 돌면 `\s*` 가 개행을 못 넘는다). 그래서 이 프로브는 파일 전체에 돌고
#: 좌표는 match 시작 줄로 낸다. 속성명은 HTML 에서 대소문자 무시라 `[iI][dD]` 로 문다.
_ID_ATTR_GAP_PATTERNS = (
    ("other-attr-suffix", r'[-a-zA-Z]id="'),
    ("single-quoted", r"id='"),
    ("unquoted-interpolation", r"id=\$\{"),
    ("selector-literal", r"\[id="),
    ("set-attribute", r'setAttribute\(\s*["\'][iI][dD]["\']'),
    ("id-property-assignment", r"\.id\s*=(?!=)"),
    ("computed-id-assignment", r"\[\s*[\"\']\s*[iI][dD]\s*[\"\']\s*\]\s*=(?!=)"),
)


#: 제품 프런트 그래프 — `scripts/extract_js_ast_axes.mjs` 의 PRODUCT_SCOPE 와 같은 문장이다.
#: `frontend/src/*.js` **비재귀**가 `frontend/src/<하위>/store.js` 신설을 조용히 축 밖에 두던
#: 구멍을 닫고, `.mjs` 를 함께 문다(오늘 0건이지만 확장자 하나가 전 축의 사각이 될 이유가 없다).
PRODUCT_JS_SCOPE = (
    "frontend/js/**/*.js", "frontend/js/**/*.mjs",
    "frontend/src/**/*.js", "frontend/src/**/*.mjs",
)
DATA_ATTR_SCOPE = (
    "frontend/js/**/*.js", "frontend/js/**/*.mjs",
    "frontend/js/**/*.ts", "frontend/js/**/*.tsx",
    "frontend/src/**/*.js", "frontend/src/**/*.mjs",
    "frontend/src/**/*.ts", "frontend/src/**/*.tsx",
)
#: selftest 트리는 제품 그래프가 아니다(`schema.js` 는 출하 번들에도 없다). 축에서 빼되
#: 원장이 `excluded_axes` 로 **소리 나게** 제외하고 크기를 프로브로 잰다.
SELFTEST_EXCLUDED = ("frontend/src/selftest/**",)
SELFTEST_SCOPE = ("frontend/src/selftest/**/*.js", "frontend/src/selftest/**/*.mjs")


def _js_id_attr_anchor_gaps(repo: Repo) -> list[str]:
    rows: list[str] = []
    for path in repo.files(PRODUCT_JS_SCOPE, SELFTEST_EXCLUDED):
        text = repo.text(path)
        if text is None:
            continue
        for name, pattern in _ID_ATTR_GAP_PATTERNS:
            # 줄 단위가 아니라 **파일 전체**에 돌린다 — prettier 가 만드는 줄바꿈이 방금 편입한
            # 형태를 그대로 무력화하던 자리다.
            for match in re.finditer(pattern, text):
                line_no = text[: match.start()].count("\n") + 1
                rows.append(f"{repo.relative(path)}:{line_no}:{name}")
    return sorted(rows)


_CONVENTION_STATE = re.compile(r"(?m)^  (?:let|var)\s+([A-Za-z_$][\w$]*)")


def _js_module_state_convention(repo: Repo) -> list[str]:
    """2칸 들여쓰기 **관례** 술어 — `test_web_dom_contract.py` 의 예산 헬퍼와 같은 눈.

    원장은 이것을 값으로 쓰지 않는다. 예산 6파일 안에서는 AST 와 정확히 일치하고(36 = 36)
    그 밖에서는 거짓양성 12·거짓음성 4를 낸다 — 두 계측의 **관계**를 원장 한자리에 두려고
    ``aliases`` 로만 싣는다.
    """
    rows: list[str] = []
    for path in repo.files(("frontend/js/**/*.js",)):
        text = repo.text(path)
        if text is None:
            continue
        rel = repo.relative(path)
        for line_no, line in enumerate(text.splitlines(), 1):
            match = _CONVENTION_STATE.match(line)
            if match:
                rows.append(f"{rel}:{line_no} {match.group(1)}")
    return sorted(rows)


_BUDGET_SCOPE = (
    "frontend/js/screens/job.js",
    "frontend/js/screens/workbench.js",
    "frontend/js/screens/editor.js",
    "frontend/js/screens/library.js",
    "frontend/js/data_picker.js",
    "frontend/js/datazone.js",
)


def _js_module_state_convention_budget(repo: Repo) -> list[str]:
    allowed = {f"{rel}" for rel in _BUDGET_SCOPE}
    return [row for row in _js_module_state_convention(repo) if row.split(":")[0] in allowed]


def _action_registry_screens(repo: Repo) -> list[str]:
    return sorted(_action_registry(repo))


def _action_registry_pairs(repo: Repo) -> list[str]:
    return sorted(
        f"{screen}/{action}"
        for screen, actions in _action_registry(repo).items()
        for action in actions
    )


def _action_registry_dynamic(repo: Repo) -> list[str]:
    """레지스트리가 모듈 상수인가 — 런타임 변형 사이트를 센다(오늘 0)."""
    rows: list[str] = []
    pattern = r"ACTION_REGISTRY\s*\[|ACTION_REGISTRY\.(?:setdefault|update|pop)"
    for path in repo.files(("src/hwpxfiller/webapp/*.py",)):
        text = repo.text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                rows.append(f"{repo.relative(path)}:{line_no}")
    return sorted(rows)


def _ring1_state_modules(repo: Repo) -> list[str]:
    return [repo.relative(path) for path in repo.files(("src/hwpxfiller/gui/*_state.py",))]


def _gui_non_state_modules(repo: Repo) -> list[str]:
    """`*_state.py` 이름 규약 밖의 링1 이웃 — 이 축이 못 보는 자리의 오늘 전수."""
    return [
        repo.relative(path)
        for path in repo.files(("src/hwpxfiller/gui/*.py",))
        if not path.name.endswith("_state.py") and path.name != "__init__.py"
    ]


_LISTENER_GAP_PATTERNS = (
    ("comment", r"(?m)^\s*(?://|\*|/\*).*(?:add|remove)EventListener"),
    ("bracket-call", r"\[[^\]\n]+\]\s*\(\s*[\"'][a-z]+[\"']\s*,"),
)


def _listener_convention_gaps(repo: Repo) -> list[str]:
    """관례 정규식이 **함께 세거나 못 보는** 것 — 주석 안 일치와 대괄호 표기 호출."""
    rows: list[str] = []
    for path in repo.files(PRODUCT_JS_SCOPE, SELFTEST_EXCLUDED):
        text = repo.text(path)
        if text is None:
            continue
        rel = repo.relative(path)
        for name, pattern in _LISTENER_GAP_PATTERNS:
            for match in re.finditer(pattern, text):
                line_no = text[: match.start()].count("\n") + 1
                rows.append(f"{rel}:{line_no}:{name}")
    return sorted(rows)


def _selftest_surface_sites(repo: Repo) -> list[str]:
    """명시 제외 축의 **크기** — 구성 지점 · 모듈 상태 · id 사이트를 한 목록으로 낸다.

    제외가 조용하면 「미분류 0」이 거짓말이 된다. 이 프로브가 그 제외를 소리 나게 만든다.
    """
    return list(repo.node_axes()["selftest_surface"])


def _action_registry(repo: Repo) -> dict[str, list[str]]:
    """`ACTION_REGISTRY` 를 **그 트리의 소스에서** 읽는다.

    import 로 읽으면 `repo_root` 를 무시하고 **설치본**을 잰다 — 같은 파일 안에서 축마다 다른
    트리를 보게 되고, 원장이 든 `scope` 가 측정 대상이 아니게 된다(editable install 이라 값만
    우연히 같았다). AST 로 읽으면 scope 가 진짜 scope 다.
    """
    path = repo.root / "src" / "hwpxfiller" / "webapp" / "action_registry.py"
    text = repo.text(path)
    if text is None:
        raise InventoryGateError(f"액션 레지스트리를 읽지 못했습니다: {path}")
    tree = ast.parse(text, filename=str(path))

    literals: dict[str, ast.Dict] = {}
    exported: str | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not names or node.value is None:
            continue
        if isinstance(node.value, ast.Dict):
            for name in names:
                literals[name] = node.value
        if "ACTION_REGISTRY" in names:
            # `MappingProxyType({screen: … for screen, actions in _REGISTRY.items()})` 처럼
            # 감싸는 층을 넘어 **어느 dict 리터럴을 내보내는지**를 이름으로 되짚는다.
            referenced = {
                child.id for child in ast.walk(node.value) if isinstance(child, ast.Name)
            }
            exported = next(
                (name for name in referenced if name in literals or name.endswith("REGISTRY")),
                None,
            )
            if isinstance(node.value, ast.Dict):
                exported = "ACTION_REGISTRY"

    source = literals.get(exported or "") or literals.get("ACTION_REGISTRY")
    if source is None:
        raise InventoryGateError(
            "ACTION_REGISTRY 가 내보내는 dict 리터럴을 찾지 못했습니다 — 레지스트리가 모듈 상수라는 "
            "이 축의 전제가 깨졌습니다."
        )
    registry: dict[str, list[str]] = {}
    for key, value in zip(source.keys, source.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise InventoryGateError("액션 레지스트리의 화면 키가 문자열 리터럴이 아닙니다.")
        registry[key.value] = _literal_dict_keys(value, literals, f"레지스트리[{key.value!r}]")
    return registry


def _literal_dict_keys(node: ast.expr, literals: dict[str, ast.Dict], where: str) -> list[str]:
    """dict 리터럴의 키를 읽되 ``**공유묶음`` 전개를 따라간다.

    `job` 화면은 `**_DATA_ZONE` 으로 공유 액션을 싣고 그 묶음이 다시 `**_ZONE_MUTATIONS` 를
    싣는다. 전개를 안 따라가면 그 화면의 액션이 조용히 줄어 값이 틀린다.
    """
    if not isinstance(node, ast.Dict):
        raise InventoryGateError(f"{where} 가 dict 리터럴이 아닙니다.")
    keys: list[str] = []
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:  # `**expr` 전개
            if not isinstance(value, ast.Name) or value.id not in literals:
                raise InventoryGateError(
                    f"{where} 의 `**` 전개가 모듈 상수 dict 가 아닙니다 — 레지스트리가 모듈 "
                    "상수라는 이 축의 전제가 깨졌습니다."
                )
            keys.extend(_literal_dict_keys(literals[value.id], literals, f"{where}/{value.id}"))
            continue
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise InventoryGateError(f"{where} 의 키가 문자열 리터럴이 아닙니다.")
        keys.append(key.value)
    return keys


EXTRACTORS: dict[str, Extractor] = {
    "html_ids": Extractor("parser", ("frontend/index.html",), _html_ids),
    "html_data_attrs": Extractor("parser", ("frontend/index.html",), _html_data_attrs),
    "html_parse_anomalies": Extractor(
        "parser", ("frontend/index.html",), _html_parse_anomalies
    ),
    "html_data_attr_elements": Extractor(
        "parser", ("frontend/index.html",), _html_data_attr_elements
    ),
    "html_data_attr_elements_without_id": Extractor(
        "parser", ("frontend/index.html",), _html_data_attr_elements_without_id
    ),
    "html_data_attr_regex_delta": Extractor(
        "regex-convention", ("frontend/index.html",), _html_data_attr_regex_delta
    ),
    "js_template_ids": Extractor(
        "ast", PRODUCT_JS_SCOPE, _js_template_ids, SELFTEST_EXCLUDED
    ),
    "js_planted_data_attrs": Extractor(
        "ast", DATA_ATTR_SCOPE, _js_planted_data_attrs, SELFTEST_EXCLUDED
    ),
    "js_data_attr_dynamic": Extractor(
        "ast", DATA_ATTR_SCOPE, _js_data_attr_dynamic, SELFTEST_EXCLUDED
    ),
    "js_id_attr_anchor_gaps": Extractor(
        "regex-convention", PRODUCT_JS_SCOPE, _js_id_attr_anchor_gaps, SELFTEST_EXCLUDED,
        tuple(name for name, _ in _ID_ATTR_GAP_PATTERNS),
    ),
    "js_module_state": Extractor(
        "ast", PRODUCT_JS_SCOPE, _js_module_state, SELFTEST_EXCLUDED
    ),
    "js_nonexported_fn_state": Extractor(
        "ast", PRODUCT_JS_SCOPE, _js_nonexported_fn_state, SELFTEST_EXCLUDED
    ),
    "selftest_surface_sites": Extractor("ast", SELFTEST_SCOPE, _selftest_surface_sites),
    "js_module_state_convention": Extractor(
        "regex-convention", ("frontend/js/**/*.js",), _js_module_state_convention
    ),
    "js_module_state_convention_budget": Extractor(
        "regex-convention", _BUDGET_SCOPE, _js_module_state_convention_budget
    ),
    "action_registry_screens": Extractor(
        "python-ast",
        ("src/hwpxfiller/webapp/action_registry.py",),
        _action_registry_screens,
    ),
    "action_registry_pairs": Extractor(
        "python-ast",
        ("src/hwpxfiller/webapp/action_registry.py",),
        _action_registry_pairs,
    ),
    "action_registry_dynamic": Extractor(
        "regex-convention", ("src/hwpxfiller/webapp/*.py",), _action_registry_dynamic
    ),
    "ring1_state_modules": Extractor(
        "python-glob", ("src/hwpxfiller/gui/*_state.py",), _ring1_state_modules
    ),
    "gui_non_state_modules": Extractor(
        "python-glob", ("src/hwpxfiller/gui/*.py",), _gui_non_state_modules
    ),
    "listener_convention_gaps": Extractor(
        "regex-convention", PRODUCT_JS_SCOPE, _listener_convention_gaps, SELFTEST_EXCLUDED,
        tuple(name for name, _ in _LISTENER_GAP_PATTERNS),
    ),
}

#: `kind = "node_extractor"` 로 선언해야 하는 추출기 — 읽는 사람이 「이 값이 얼마나 믿을
#: 만한가」를 이름이 아니라 종류에서 읽게 한다.
_NODE_BACKED = frozenset(
    name for name, extractor in EXTRACTORS.items() if extractor.backing == "ast"
)


# ──────────────────────────────────────────────────────────────────────────
# 정규식 술어 — 패턴·범위·단위가 **원장 안에** 산다
# ──────────────────────────────────────────────────────────────────────────


def _regex_sites(repo: Repo, pattern: str, scope: tuple[str, ...], granularity: str,
                 excluded: tuple[str, ...] = ()) -> list[str]:
    """정규식 술어를 사이트 좌표로 편다.

    ``per-line`` 은 줄 단위로 돌린다 — 셸 ``grep`` 과 같은 눈이라 줄 끝 대입에서 값이 갈리는
    자리(`innerHTML` 61 vs 50)를 원장이 재현할 수 있다.
    """
    compiled = re.compile(pattern)
    rows: list[str] = []
    for path in repo.files(scope, excluded):
        text = repo.text(path)
        if text is None:
            continue
        rel = repo.relative(path)
        if granularity == "per-occurrence":
            seen: Counter[int] = Counter()
            for match in compiled.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                seen[line_no] += 1
                index = seen[line_no]
                rows.append(f"{rel}:{line_no}" + (f"#{index}" if index > 1 else ""))
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            matches = list(compiled.finditer(line))
            if not matches:
                continue
            if granularity == "per-matching-line":
                rows.append(f"{rel}:{line_no}")
                continue
            for index, _ in enumerate(matches, 1):
                rows.append(f"{rel}:{line_no}" + (f"#{index}" if index > 1 else ""))
    return rows


def _measure(repo: Repo, predicate: dict[str, Any], scope: tuple[str, ...],
             axis_members: dict[str, list[str]] | None = None,
             excluded: tuple[str, ...] = ()) -> list[str]:
    """술어 하나를 저장소에 재실행해 **멤버 키 목록**을 돌려준다."""
    kind = predicate.get("kind")
    if kind in {"extractor", "node_extractor"}:
        name = predicate.get("name")
        extractor = EXTRACTORS.get(name or "")
        if extractor is None:
            raise InventoryGateError(f"등록되지 않은 추출기: {name!r}")
        return list(extractor.run(repo))
    if kind == "regex":
        return _regex_sites(
            repo, predicate["pattern"], scope,
            predicate.get("granularity", "per-occurrence"), excluded,
        )
    if kind == "derived":
        axis = predicate.get("axis")
        if axis_members is None or axis not in axis_members:
            raise InventoryGateError(f"파생 술어가 가리키는 축을 못 잽니다: {axis!r}")
        members = axis_members[axis]
        return [member for member in members if _member_in_scope(member, scope, excluded)]
    raise InventoryGateError(f"알 수 없는 술어 종류: {kind!r}")


def _member_in_scope(member: str, scope: tuple[str, ...], excluded: tuple[str, ...] = ()) -> bool:
    """멤버 키의 경로 접두를 scope 글롭에 맞춘다 — 경로가 없는 멤버는 전부 통과.

    「전부 통과」가 곧 사각이다(경로 없는 축에서 `scope` 가 장식이 된다). 그래서 그런 축의
    파생 계측은 **scope 가 축과 정확히 같아야** 하고, 그 강제는 :func:`_check_metric` 이 진다.
    """
    head = member.split(":", 1)[0].split(" ", 1)[0]
    if "/" not in head:
        return True
    if any(_glob_match(head, pattern.removesuffix("/**") + "/**") for pattern in excluded):
        return False
    return any(_glob_match(head, pattern) for pattern in scope)


def _glob_match(path: str, pattern: str) -> bool:
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
    regex = regex.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(regex, path) is not None


# ──────────────────────────────────────────────────────────────────────────
# 보고서
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class AxisReport:
    axis: str
    measured: int = 0
    covered: int = 0
    unclassified: list[str] = field(default_factory=list)
    ghost: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    members_mismatch: list[str] = field(default_factory=list)
    blind_spot_delta: list[str] = field(default_factory=list)


@dataclass
class Report:
    axes: dict[str, AxisReport] = field(default_factory=dict)
    metric_mismatch: list[str] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)
    unknown_evidence: int = 0
    node_rows: int = 0

    @property
    def failures(self) -> list[str]:
        rows = list(self.structural)
        for axis in self.axes.values():
            rows += [f"[{axis.axis}] 미분류: {member}" for member in axis.unclassified]
            rows += [f"[{axis.axis}] 유령 행: {member}" for member in axis.ghost]
            rows += [f"[{axis.axis}] 중복 소유: {member}" for member in axis.duplicate]
            rows += [f"[{axis.axis}] {message}" for message in axis.members_mismatch]
            rows += [f"[{axis.axis}] {message}" for message in axis.blind_spot_delta]
        rows += self.metric_mismatch
        return rows

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "node_rows": self.node_rows,
            "unknown_evidence": self.unknown_evidence,
            "axes": {
                name: {
                    "measured": axis.measured,
                    "covered": axis.covered,
                    "unclassified": axis.unclassified,
                    "ghost": axis.ghost,
                    "duplicate": axis.duplicate,
                    "members_mismatch": axis.members_mismatch,
                    "blind_spot_delta": axis.blind_spot_delta,
                }
                for name, axis in self.axes.items()
            },
            "metric_mismatch": self.metric_mismatch,
            "structural": self.structural,
            "failures": self.failures,
        }


# ──────────────────────────────────────────────────────────────────────────
# 구조 술어
# ──────────────────────────────────────────────────────────────────────────


def _require_predicate_triple(where: str, item: dict[str, Any], report: Report) -> bool:
    """술어 3종 필수, 예외 0. ``derived`` 도 ``predicate.kind`` 의 한 값이라 면제가 아니다."""
    ok = True
    for field_name in ("predicate", "scope", "unit"):
        value = item.get(field_name)
        if value is None or (isinstance(value, (str, list)) and len(value) == 0):
            report.structural.append(
                f"{where}: `{field_name}` 이(가) 없습니다 — 값만 있는 항목은 성립하지 않습니다."
            )
            ok = False
    predicate = item.get("predicate")
    if not isinstance(predicate, dict) or "kind" not in predicate:
        report.structural.append(f"{where}: `predicate.kind` 가 없습니다.")
        return False
    kind = predicate["kind"]
    if kind == "regex":
        for field_name in ("pattern", "flavor", "granularity"):
            if not predicate.get(field_name):
                report.structural.append(
                    f"{where}: `backing=regex-convention` 술어는 `predicate.{field_name}` 을 듭니다."
                )
                ok = False
        if predicate.get("granularity") not in GRANULARITIES | {None}:
            report.structural.append(
                f"{where}: 알 수 없는 granularity {predicate.get('granularity')!r}."
            )
            ok = False
    elif kind in {"extractor", "node_extractor"}:
        name = predicate.get("name")
        extractor = EXTRACTORS.get(name or "")
        if extractor is None:
            report.structural.append(f"{where}: 등록되지 않은 추출기 {name!r}.")
            return False
        if (kind == "node_extractor") != (name in _NODE_BACKED):
            report.structural.append(
                f"{where}: 추출기 {name!r} 의 backing 은 {extractor.backing!r} 인데 "
                f"`kind={kind}` 로 선언됐습니다."
            )
            ok = False
        declared = tuple(item.get("scope") or ())
        if declared != extractor.scope:
            report.structural.append(
                f"{where}: 추출기 {name!r} 의 scope 는 {list(extractor.scope)} 인데 "
                f"원장은 {list(declared)} 라고 적었습니다."
            )
            ok = False
        declared_excluded = tuple(item.get("scope_excluded") or ())
        if declared_excluded != extractor.scope_excluded:
            report.structural.append(
                f"{where}: 추출기 {name!r} 의 scope_excluded 는 "
                f"{list(extractor.scope_excluded)} 인데 원장은 {list(declared_excluded)} "
                "라고 적었습니다."
            )
            ok = False
    elif kind != "derived":
        report.structural.append(f"{where}: 알 수 없는 술어 종류 {kind!r}.")
        ok = False
    return ok


def _check_evidence(node_id: str, evidence: Any, repo: Repo, report: Report) -> None:
    """``{file, line, anchor}`` 셋을 실제로 읽는다 — 앵커가 그 줄에 있어야 증거다."""
    if not isinstance(evidence, list) or not evidence:
        report.structural.append(f"노드 {node_id}: `evidence` 가 비었습니다.")
        return
    for item in evidence:
        if not isinstance(item, dict) or {"file", "line", "anchor"} - item.keys():
            report.structural.append(
                f"노드 {node_id}: `evidence` 는 {{file, line, anchor}} 여야 합니다 — {item!r}"
            )
            continue
        path = repo.root / str(item["file"])
        if not path.is_file():
            report.structural.append(f"노드 {node_id}: 증거 파일이 없습니다 — {item['file']}")
            continue
        text = repo.text(path)
        if text is None:
            report.structural.append(f"노드 {node_id}: 증거 파일을 읽지 못했습니다 — {item['file']}")
            continue
        lines = text.splitlines()
        line_no = int(item["line"])
        if not 1 <= line_no <= len(lines):
            report.structural.append(
                f"노드 {node_id}: 증거 좌표가 파일 밖입니다 — "
                f"{item['file']}:{line_no} (총 {len(lines)}행)"
            )
            continue
        anchor = str(item["anchor"])
        if anchor not in lines[line_no - 1]:
            report.structural.append(
                f"노드 {node_id}: 증거 앵커가 그 줄에 없습니다 — "
                f"{item['file']}:{line_no} 에서 {anchor!r} 를 찾지 못했습니다."
            )
            continue
        # 앵커가 파일에서 유일하지 않으면 「그 줄에 있다」는 좌표를 지키지 못한다 —
        # 반복 토큰 구간에서는 줄이 밀려도 초록이었다. 유일하지 않으면 `occurrence` 로
        # **몇 번째 줄인지**를 함께 든다.
        hits = [n for n, line in enumerate(lines, 1) if anchor in line]
        if len(hits) == 1:
            if item.get("occurrence") is not None:
                report.structural.append(
                    f"노드 {node_id}: 앵커가 유일한데 `occurrence` 를 들었습니다 — "
                    f"{item['file']}:{line_no}"
                )
            continue
        occurrence = item.get("occurrence")
        if occurrence is None:
            report.structural.append(
                f"노드 {node_id}: 증거 앵커가 유일하지 않습니다 — "
                f"{item['file']} 안에서 {anchor!r} 가 {len(hits)}줄에 있습니다. "
                "`occurrence` 로 몇 번째인지를 들거나 유일한 앵커로 바꾸세요."
            )
            continue
        index = int(occurrence)
        if not 1 <= index <= len(hits) or hits[index - 1] != line_no:
            report.structural.append(
                f"노드 {node_id}: 증거의 occurrence 가 어긋납니다 — "
                f"{item['file']} 의 {anchor!r} {index}번째는 "
                f"{hits[index - 1] if 1 <= index <= len(hits) else '없음'}행인데 "
                f"원장은 {line_no}행이라고 적었습니다."
            )


def _check_verification(node_id: str, entries: Any, repo: Repo, report: Report) -> None:
    """``verification`` 은 「오늘 이 노드를 보는 테스트」다.

    ``none`` 은 **명시값**이다 — 공란과 다르다. 나머지는 `파일` 또는 `파일::테스트` 이고
    게이트가 그 파일과 이름의 실재를 확인한다. 확인하지 않으면 이름이 죽은 뒤에도 원장은
    초록으로 「검증된다」고 말한다.
    """
    if not isinstance(entries, list) or not entries:
        report.structural.append(f"노드 {node_id}: `verification` 이 비었습니다(없으면 `none` 명시값).")
        return
    for entry in entries:
        if entry == "none":
            continue
        rel, _, test_name = str(entry).partition("::")
        path = repo.root / rel
        if not path.is_file():
            report.structural.append(f"노드 {node_id}: 검증 자산이 없습니다 — {entry}")
            continue
        if test_name:
            text = _read_text(path) or ""
            if f"def {test_name}(" not in text:
                report.structural.append(
                    f"노드 {node_id}: 검증 자산에 그 테스트가 없습니다 — {entry}"
                )


def _check_node_shape(node: dict[str, Any], declared_axes: set[str], report: Report) -> None:
    node_id = str(node.get("id", "<id 없음>"))
    for field_name in ("id", "kind", "axis", "selector", "classification", "verification"):
        if not node.get(field_name):
            report.structural.append(f"노드 {node_id}: `{field_name}` 이(가) 없습니다.")
    kind = node.get("kind")
    if kind is not None and kind not in NODE_KINDS:
        report.structural.append(
            f"노드 {node_id}: `kind` 는 {sorted(NODE_KINDS)} 중 하나여야 합니다 — {kind!r}"
        )
    classification = node.get("classification")
    if classification is not None and classification not in CLASSIFICATIONS:
        report.structural.append(
            f"노드 {node_id}: `classification` 은 소문자 5종 {sorted(CLASSIFICATIONS)} 중 "
            f"하나여야 합니다 — {classification!r}"
        )
    axis = node.get("axis")
    if axis is not None and axis not in declared_axes:
        report.structural.append(f"노드 {node_id}: 선언되지 않은 축 {axis!r}.")

    # 배타성(구조 술어 9)
    if classification == "react" and not node.get("handoff_slice"):
        report.structural.append(
            f"노드 {node_id}: `classification=react` 행은 `handoff_slice` 를 듭니다."
        )
    slice_name = node.get("handoff_slice")
    if slice_name and slice_name not in HANDOFF_SLICES:
        report.structural.append(
            f"노드 {node_id}: 알 수 없는 이관 슬라이스 {slice_name!r} — "
            f"R2~R5 구현 슬라이스여야 합니다."
        )
    if classification in {"python_product", "host", "retire"}:
        handoff = node.get("p_handoff")
        if handoff not in P_HANDOFF_VALUES:
            report.structural.append(
                f"노드 {node_id}: `classification={classification}` 행은 "
                f"`p_handoff` 를 yes|no 로 듭니다 — {handoff!r}"
            )
        if classification == "retire" and handoff == "yes":
            report.structural.append(
                f"노드 {node_id}: `retire` 행의 `p_handoff` 는 `no` 로 강제됩니다."
            )
    if classification == "p_review_required":
        review = node.get("p_review")
        if not isinstance(review, dict):
            report.structural.append(
                f"노드 {node_id}: `p_review_required` 행은 5증거 표 `[node.p_review]` 를 듭니다."
            )
        else:
            for field_name in P_REVIEW_FIELDS:
                value = review.get(field_name)
                if not value:
                    report.structural.append(
                        f"노드 {node_id}: `p_review.{field_name}` 이(가) 공란입니다 — "
                        "「모름」은 공란이 아니라 `unknown` 명시값입니다."
                    )
                elif value == "unknown" or value.startswith("unknown "):
                    report.unknown_evidence += 1


# ──────────────────────────────────────────────────────────────────────────
# 폐포
# ──────────────────────────────────────────────────────────────────────────


def _fold_dom(repo: Repo, containers: set[str], exact_ids: set[str]) -> dict[str, list[str]]:
    """자신을 포함하지 않는 **가장 가까운 선언된 컨테이너**에 배정한다.

    컨테이너 루트 자신은 자기 컨테이너에 속하지 않으므로 반드시 위쪽 어딘가에 `exact` 행이나
    바깥 컨테이너가 있어야 한다 — 그 규칙 때문에 루트 직속 9는 전부 `exact` 로 명시된다.
    """
    parsed = repo.html()
    assignment: dict[str, list[str]] = {name: [] for name in containers}
    assignment["ROOT"] = []
    for element_id in parsed.ids:
        if element_id in exact_ids:
            continue
        owner = "ROOT"
        for ancestor in reversed(parsed.ancestors.get(element_id, ())):
            if ancestor in containers:
                owner = ancestor
                break
        assignment[owner].append(element_id)
    return assignment


def _axis_coverage(
    axis_name: str,
    axis_decl: dict[str, Any],
    nodes: list[dict[str, Any]],
    measured: list[str],
    repo: Repo,
) -> AxisReport:
    result = AxisReport(axis=axis_name, measured=len(measured))
    measured_set = set(measured)

    exact_ids: set[str] = set()
    for node in nodes:
        selector = node.get("selector") or {}
        if selector.get("kind") == "exact":
            exact_ids.update(selector.get("members") or [])

    folded: dict[str, list[str]] = {}
    if axis_decl.get("fold"):
        containers = {
            (node.get("selector") or {}).get("root")
            for node in nodes
            if (node.get("selector") or {}).get("kind") == "subtree"
        }
        folded = _fold_dom(repo, {name for name in containers if name}, exact_ids)

    covered: Counter[str] = Counter()
    for node in nodes:
        node_id = str(node.get("id"))
        selector = node.get("selector") or {}
        if selector.get("kind") == "exact":
            covered.update(selector.get("members") or [])
        elif selector.get("kind") == "subtree":
            root = selector.get("root")
            members = folded.get(root, [])
            covered.update(members)
            expected = selector.get("members_expected")
            if expected is None:
                result.members_mismatch.append(
                    f"접힌 행 {node_id}: `members_expected` 가 없습니다 — "
                    "접기만 있으면 컨테이너 안쪽 성장이 영영 안 붉습니다."
                )
            elif int(expected) != len(members):
                result.members_mismatch.append(
                    f"접힌 행 {node_id}(root={root}): members_expected={expected} 인데 "
                    f"실제 배정은 {len(members)} 입니다."
                )
            if root not in measured_set and root is not None:
                result.ghost.append(f"{root} (컨테이너 루트가 저장소에 없습니다: {node_id})")
        else:
            result.members_mismatch.append(
                f"노드 {node_id}: 알 수 없는 selector 종류 {selector.get('kind')!r}."
            )

    result.covered = len(covered)
    result.duplicate = sorted(name for name, count in covered.items() if count > 1)
    result.unclassified = sorted(measured_set - set(covered))
    result.ghost += sorted(set(covered) - measured_set)
    return result


def _check_coverage_claim(
    axis_name: str,
    field: str,
    label: str,
    claim: Any,
    repo: Repo,
    axis_members: dict[str, list[str]],
    report: Report,
    axis_report: AxisReport,
    required: bool,
) -> None:
    """`blind_spot`(못 보는 것)과 `false_positive`(잘못 보는 것)를 같은 규칙으로 검사한다.

    술어는 값뿐 아니라 **자기 커버리지**를 진술해야 하고, 커버리지는 두 방향이다. 한 방향만
    들면 「18개 팩토리」처럼 값은 옳고 이름이 틀린 자리를 못 잡는다.
    """
    if claim is None:
        if required:
            report.structural.append(
                f"축 {axis_name}: `{field}` 이(가) 없습니다 — 추출기 항목은 「{label}」을 데이터로 "
                "듭니다(없으면 `current = 0` 과 그것을 세는 프로브를)."
            )
        return
    if not isinstance(claim, dict):
        report.structural.append(f"축 {axis_name}: `{field}` 은 표여야 합니다.")
        return
    for field_name in ("description", "probe", "scope", "current"):
        if claim.get(field_name) is None:
            report.structural.append(f"축 {axis_name}: `{field}.{field_name}` 이(가) 없습니다.")
            return
    if not _require_predicate_triple(
        f"축 {axis_name} 의 {field}",
        {
            "predicate": claim["probe"],
            "scope": claim["scope"],
            "scope_excluded": claim.get("scope_excluded"),
            "unit": claim.get("unit"),
        },
        report,
    ):
        return
    try:
        found = _measure(
            repo, claim["probe"], tuple(claim["scope"]), axis_members,
            tuple(claim.get("scope_excluded") or ()),
        )
    except InventoryGateError as exc:
        report.structural.append(f"축 {axis_name}: {field} 프로브 실패 — {exc}")
        return
    probe = claim["probe"]
    if probe.get("kind") in {"extractor", "node_extractor"}:
        extractor = EXTRACTORS.get(str(probe.get("name")))
        if extractor is not None and extractor.forms:
            declared_forms = list(claim.get("known_forms") or [])
            if declared_forms != list(extractor.forms):
                report.structural.append(
                    f"축 {axis_name}: `{field}.known_forms` 가 추출기 "
                    f"{probe.get('name')!r} 의 형태 전수와 다릅니다 — 원장의 설명이 자기가 "
                    "기술하는 추출기와 어긋납니다.\n"
                    f"  원장: {declared_forms}\n  추출기: {list(extractor.forms)}"
                )
    if len(found) != int(claim["current"]):
        axis_report.blind_spot_delta.append(
            f"{label}이 움직였습니다({field}): 기록 {claim['current']} → 실측 {len(found)}. "
            f"실측 전수: {sorted(found)}"
        )
        return
    declared_members = claim.get("members")
    if declared_members is None and found:
        report.structural.append(
            f"축 {axis_name}: `{field}.members` 가 없습니다 — 크기가 0이 아니면 **무엇이** 그 "
            "안에 있는지를 들어야 다음 사람이 자란 것과 옮겨간 것을 가릅니다."
        )
        return
    if declared_members is not None and sorted(declared_members) != sorted(found):
        axis_report.blind_spot_delta.append(
            f"{label} 멤버가 어긋납니다({field}).\n"
            f"  기록에만: {sorted(set(declared_members) - set(found))}\n"
            f"  실측에만: {sorted(set(found) - set(declared_members))}"
        )


def _check_blind_spot(
    axis_name: str,
    axis_decl: dict[str, Any],
    repo: Repo,
    axis_members: dict[str, list[str]],
    report: Report,
    axis_report: AxisReport,
) -> None:
    _check_coverage_claim(
        axis_name, "blind_spot", "사각", axis_decl.get("blind_spot"),
        repo, axis_members, report, axis_report, required=True,
    )
    _check_coverage_claim(
        axis_name, "false_positive", "오검", axis_decl.get("false_positive"),
        repo, axis_members, report, axis_report, required=False,
    )


def _check_review_items(document: dict[str, Any], repo: Repo, report: Report) -> None:
    """축의 멤버가 아니면서 **사람 판정을 요구하는** 사실.

    「비소유」의 실행 규칙은 발견한 결함을 고치지 않고 기록하며 수정 소유 단계를 지목하는
    것이다. 그 기록이 산문 각주로 남으면 늙는다 — 여기서는 소유자와 증거 앵커가 게이트 대상이다.
    """
    items = list(document.get("review_item") or [])
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id", "<id 없음>"))
        if item_id in seen:
            report.structural.append(f"판정 요구 항목 id 가 중복입니다: {item_id}")
        seen.add(item_id)
        for field_name in ("id", "subject", "owner"):
            if not item.get(field_name):
                report.structural.append(f"판정 요구 항목 {item_id}: `{field_name}` 이(가) 없습니다.")
        # `classification` 은 노드 표에서 「React 이후 이 노드의 소유자」다. 같은 이름을 여기
        # 붙이면 「이 사실의 처분을 누가 지는가」라는 **다른 명제**를 지게 되고, V7 이 두 열을
        # 합쳐 없앤 형상이 「한 이름 · 두 표」로 되돌아온다. 그래서 이 표는 그 이름을 안 쓴다.
        if "classification" in item:
            report.structural.append(
                f"판정 요구 항목 {item_id}: `classification` 은 노드 표의 이름입니다 — "
                "여기서는 `owner`(처분 소유)와 `requires_p_review`(5증거 요구)를 씁니다."
            )
        requires = item.get("requires_p_review")
        if not isinstance(requires, bool):
            report.structural.append(
                f"판정 요구 항목 {item_id}: `requires_p_review` 를 true|false 로 듭니다."
            )
        resolved = item.get("resolved")
        if not isinstance(resolved, bool):
            report.structural.append(
                f"판정 요구 항목 {item_id}: `resolved` 를 true|false 로 듭니다."
            )
        elif resolved and not item.get("disposition"):
            report.structural.append(
                f"판정 요구 항목 {item_id}: `resolved = true` 는 `disposition` 을 듭니다."
            )
        owner = item.get("owner")
        if owner and owner not in HANDOFF_SLICES:
            report.structural.append(
                f"판정 요구 항목 {item_id}: 알 수 없는 소유 슬라이스 {owner!r}."
            )
        _check_evidence(item_id, item.get("evidence"), repo, report)
        if requires is True:
            review = item.get("p_review")
            if not isinstance(review, dict):
                report.structural.append(
                    f"판정 요구 항목 {item_id}: `requires_p_review = true` 는 5증거 표를 듭니다."
                )
                continue
            for field_name in P_REVIEW_FIELDS:
                value = review.get(field_name)
                if not value:
                    report.structural.append(
                        f"판정 요구 항목 {item_id}: `p_review.{field_name}` 이(가) 공란입니다 — "
                        "「모름」은 공란이 아니라 `unknown` 명시값입니다."
                    )
                elif value == "unknown" or value.startswith("unknown "):
                    report.unknown_evidence += 1


# ──────────────────────────────────────────────────────────────────────────
# 계측
# ──────────────────────────────────────────────────────────────────────────


def _check_metric(
    metric: dict[str, Any],
    repo: Repo,
    axis_members: dict[str, list[str]],
    declared_axes: dict[str, Any],
    report: Report,
) -> None:
    metric_id = str(metric.get("id", "<id 없음>"))
    if metric.get("value") is None:
        report.structural.append(f"계측 {metric_id}: `value` 가 없습니다.")
    items: list[tuple[str, dict[str, Any]]] = [(metric_id, metric)]
    for index, alias in enumerate(metric.get("aliases") or [], 1):
        items.append((f"{metric_id}/alias[{index}]", alias))
    for where, item in items:
        if not _require_predicate_triple(f"계측 {where}", item, report):
            continue
        predicate = item["predicate"]
        if predicate.get("kind") == "derived":
            axis_name = predicate.get("axis")
            axis_decl = declared_axes.get(axis_name or "")
            if not isinstance(axis_decl, dict):
                report.metric_mismatch.append(
                    f"계측 {where}: 파생 술어가 선언되지 않은 축 {axis_name!r} 을 가리킵니다."
                )
                continue
            members = axis_members.get(axis_name or "", [])
            pathless = any("/" not in m.split(":", 1)[0].split(" ", 1)[0] for m in members)
            if pathless and tuple(item["scope"]) != tuple(axis_decl.get("scope") or ()):
                # 멤버 키에 경로가 없는 축(요소 id·속성 이름·화면 이름)에서는 scope 필터가
                # 아무것도 거르지 못한다 — 그러면 v2 §2 의 세 필드 중 하나가 장식이 된다.
                report.metric_mismatch.append(
                    f"계측 {where}: 축 {axis_name} 의 멤버에 경로가 없어 scope 필터가 아무것도 "
                    f"거르지 못합니다. 파생 계측은 축 scope {list(axis_decl.get('scope') or ())} "
                    f"를 그대로 상속해야 하는데 {list(item['scope'])} 라고 적었습니다."
                )
                continue
        try:
            found = _measure(
                repo, predicate, tuple(item["scope"]), axis_members,
                tuple(item.get("scope_excluded") or ()),
            )
        except InventoryGateError as exc:
            report.metric_mismatch.append(f"계측 {where}: 재실측 실패 — {exc}")
            continue
        recorded = item.get("value")
        if recorded is None or int(recorded) != len(found):
            report.metric_mismatch.append(
                f"계측 {where}: 기록 {recorded} → 재실측 {len(found)} (술어 {item['predicate']}, "
                f"scope {item['scope']})"
            )


# ──────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────


def load_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise InventoryGateError(f"원장이 없습니다: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def axis_measurement_digest(axis_decl: dict[str, Any]) -> str:
    """축의 **측정 계약**만 정규화해 지문을 낸다.

    값(`current`·`members`)과 산문(`unit`·`description`·`judgment`)은 뺀다 — 그것들은 매번
    재실측되거나 사람이 읽는 것이고, 지문이 겨누는 것은 「무엇을 어떻게 재는가」다.
    프로브를 통째로 지우는 것도 지문을 바꾸므로 `false_positive` 삭제가 여기서 붉는다.
    """

    def measurement(item: Any) -> Any:
        if not isinstance(item, dict):
            return None
        return {
            "probe": item.get("probe"),
            "scope": list(item.get("scope") or []),
            "scope_excluded": list(item.get("scope_excluded") or []),
        }

    payload = {
        "predicate": axis_decl.get("predicate"),
        "scope": list(axis_decl.get("scope") or []),
        "scope_excluded": list(axis_decl.get("scope_excluded") or []),
        "fold": axis_decl.get("fold"),
        "blind_spot": measurement(axis_decl.get("blind_spot")),
        "false_positive": measurement(axis_decl.get("false_positive")),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _product_tree_coverage(
    document: dict[str, Any], repo: Repo, report: Report
) -> None:
    """게이트가 **제품 트리를 스스로 열거**하고 전수 피복을 주장한다.

    폐포 검사는 집합 기반이라 옳게 돌지만, 측정 집합 M 자체가 원장이 선언한 scope 에서 나온다.
    scope 를 좁히면 M 도 함께 줄어 폐포는 계속 참이다 — 분모를 밖으로 뺐어도 **정의역**이 안에
    있으면 같은 자리로 돌아온다. 그래서 여기서는 원장에 묻지 않고 트리를 직접 센다.
    """
    enumerated = {repo.relative(path) for path in repo.files(PRODUCT_TREE_GLOBS)}
    covered: set[str] = set()
    for decl in (document.get("axes") or {}).values():
        if not isinstance(decl, dict) or not decl.get("scope"):
            continue
        covered.update(
            repo.relative(path)
            for path in repo.files(
                tuple(decl["scope"]), tuple(decl.get("scope_excluded") or ())
            )
        )
    for excluded in document.get("excluded_axes") or []:
        for pattern in excluded.get("covers") or []:
            covered.update(repo.relative(path) for path in repo.files((str(pattern),)))
    uncovered = sorted(enumerated - covered)
    if uncovered:
        report.structural.append(
            "제품 트리에 **어떤 축의 scope 에도 명시 제외에도 안 덮인 파일**이 있습니다 — "
            "scope 를 좁히면 측정 집합이 함께 줄어 폐포가 조용해지므로, 전수 피복이 1차 방벽입니다.\n"
            + "\n".join(f"  덮이지 않음: {rel}" for rel in uncovered)
        )


def _check_scope_limitation(
    axis_name: str, axis_decl: dict[str, Any], report: Report
) -> None:
    """제품보다 좁은 scope 를 든 축은 **무엇을 못 보는지**를 소유자와 함께 든다.

    제품 트리 전수 피복은 「그 파일이 **어떤** 축에 속하는가」만 묻는다. 그래서 `modal.js` 에
    새 푸시 구독이 생겨도 그 파일은 이미 다른 축들에 덮여 있어 조용하다. 여기서 scope 를
    넓히면 축의 단위가 흐려지므로, 넓히는 대신 **그 한계를 정직하게 선언**한다.
    선언이 산문 각주면 늙는다 — 필드로 두고 사라지면 붉힌다.
    """
    owner = NARROW_SCOPE_AXES.get(axis_name)
    if owner is None:
        return
    limitation = axis_decl.get("scope_limitation")
    if not isinstance(limitation, dict):
        report.structural.append(
            f"축 {axis_name}: `scope_limitation` 이 없습니다 — 제품 트리보다 좁은 scope 는 "
            "「이 밖에 생기면 이 축은 못 본다」를 소유자와 함께 적어야 합니다."
        )
        return
    if not limitation.get("statement"):
        report.structural.append(f"축 {axis_name}: `scope_limitation.statement` 이 비었습니다.")
    if limitation.get("owner") != owner:
        report.structural.append(
            f"축 {axis_name}: `scope_limitation.owner` 가 {limitation.get('owner')!r} 인데 "
            f"게이트는 {owner!r} 를 듭니다 — 한계의 소유자는 원장이 혼자 정하지 않습니다."
        )


def _check_cross_axis_overlap(
    document: dict[str, Any], axis_members: dict[str, list[str]], report: Report
) -> None:
    """축을 가로질러 같은 좌표를 세는 자리를 **실측에서 유도**해 선언과 대조한다.

    선언만 있고 검사가 없으면 신설 필드가 「거짓을 적기 쉬운 자리」가 된다.
    """
    owners: dict[str, list[str]] = {}
    for axis_name, members in axis_members.items():
        for member in members:
            owners.setdefault(member, []).append(axis_name)
    measured = {
        member: sorted(axes) for member, axes in owners.items() if len(axes) > 1
    }
    declared = {
        str(row.get("member")): sorted(row.get("axes") or [])
        for row in document.get("cross_axis_overlap") or []
    }
    if declared != measured:
        report.structural.append(
            "`cross_axis_overlap` 이 실측과 다릅니다 — 축을 가로지르는 겹침은 선언이 아니라 "
            "측정에서 나와야 합니다.\n"
            f"  선언에만: {sorted(set(declared) - set(measured))}\n"
            f"  실측에만: {sorted(set(measured) - set(declared))}\n"
            f"  축 쌍이 다름: "
            f"{sorted(m for m in set(declared) & set(measured) if declared[m] != measured[m])}"
        )
    for row in document.get("cross_axis_overlap") or []:
        if not row.get("reason"):
            report.structural.append(
                f"교차 겹침 {row.get('member')}: `reason` 이 없습니다 — 겹침은 사고일 수도 "
                "설계일 수도 있고, 그것을 가르는 것이 이 필드입니다."
            )


def _check_unoccupied_classifications(
    document: dict[str, Any], report: Report
) -> None:
    """「오늘 점유자가 없는 분류값」도 선언이 아니라 측정이어야 한다."""
    used = {
        str(node.get("classification"))
        for node in document.get("node") or []
        if node.get("classification")
    }
    measured = sorted(CLASSIFICATIONS - used)
    declared = sorted(document.get("unoccupied_classifications") or [])
    if declared != measured:
        report.structural.append(
            "`unoccupied_classifications` 가 실측과 다릅니다 — 부재를 데이터로 적는 습관은 "
            "그 부재를 세야 성립합니다.\n"
            f"  선언: {declared}\n  실측: {measured}"
        )


def _referenced_extractors(document: dict[str, Any]) -> set[str]:
    """원장이 실제로 쓰는 추출기 이름 전수 — 축·사각·오검·제외 크기·계측·alias 를 다 훑는다."""
    names: set[str] = set()

    def scan(item: Any) -> None:
        if isinstance(item, dict):
            for key in ("predicate", "probe"):
                predicate = item.get(key)
                if isinstance(predicate, dict) and predicate.get("name"):
                    names.add(str(predicate["name"]))
            for value in item.values():
                scan(value)
        elif isinstance(item, list):
            for value in item:
                scan(value)

    scan(document.get("axes"))
    scan(document.get("metric"))
    scan(document.get("excluded_axes"))
    return names


def check(
    document: dict[str, Any],
    repo_root: Path,
    axes: list[str] | None = None,
    metrics: list[str] | None = None,
) -> Report:
    """원장을 저장소에 재실행한다.

    ``axes``·``metrics`` 는 **음성 대조가 부분 트리를 쓰기 위한** 선택자다. 없는 파일 때문에
    무관한 축이 죽으면 그 음성 대조는 자기가 겨눈 좌표를 증명하지 못한다.
    """
    repo = Repo(repo_root)
    report = Report()

    if document.get("schema") != 1:
        report.structural.append(f"`schema` 가 1 이 아닙니다 — {document.get('schema')!r}")
    for field_name in ("baseline_sha", "scope_statement"):
        if not document.get(field_name):
            report.structural.append(f"머리말 `{field_name}` 이(가) 없습니다.")
    baseline = str(document.get("baseline_sha") or "")
    if baseline and baseline != EXPECTED_BASELINE_SHA:
        report.structural.append(
            f"`baseline_sha` 가 게이트가 든 기준선과 다릅니다 — 원장 {baseline!r} vs "
            f"게이트 {EXPECTED_BASELINE_SHA!r}. 재고정은 값 하나를 고치는 일이 아니라 중앙 "
            "판정이 붙는 사건입니다."
        )
    if document.get("repo_wide_metrics") is None:
        report.structural.append(
            "머리말 `repo_wide_metrics` 가 없습니다 — 저장소 전수 scope 계측이 오늘 몇 개인지를 "
            "데이터로 들어야 합니다(0이면 빈 배열)."
        )

    # `[extractors.*]` 는 읽는 사람에게 「이 값이 얼마나 믿을 만한가」를 말하는 표다. 코드의
    # 실제 backing 과 어긋나면 그 설명이 늙는다 — 산문이 아니라 대조 대상으로 둔다.
    declared_extractors = dict(document.get("extractors") or {})
    for name, entry in sorted(declared_extractors.items()):
        extractor = EXTRACTORS.get(name)
        if extractor is None:
            report.structural.append(f"추출기 표에 등록되지 않은 이름이 있습니다: {name}")
            continue
        if entry.get("backing") != extractor.backing:
            report.structural.append(
                f"추출기 {name}: 원장이 backing 을 {entry.get('backing')!r} 이라 적었는데 구현은 "
                f"{extractor.backing!r} 입니다."
            )
        if not entry.get("implementation"):
            report.structural.append(f"추출기 {name}: `implementation` 이 없습니다.")
    for name in sorted(_referenced_extractors(document) - set(declared_extractors)):
        report.structural.append(
            f"추출기 {name}: 원장이 쓰는데 `[extractors.{name}]` 설명이 없습니다."
        )

    declared_axes = dict(document.get("axes") or {})

    # ── 1차 방벽: 제품 트리 전수 피복 ────────────────────────────────────
    if axes is None:
        _product_tree_coverage(document, repo, report)
        _check_unoccupied_classifications(document, report)

    # ── 측정 계약 지문 — 원장은 값을, 게이트는 술어를 든다 ────────────────
    for axis_name in sorted(set(declared_axes) & set(AXIS_DIGESTS)):
        actual = axis_measurement_digest(declared_axes[axis_name])
        if actual != AXIS_DIGESTS[axis_name]:
            report.structural.append(
                f"축 {axis_name}: 측정 계약이 게이트가 든 지문과 다릅니다 — "
                f"기록 {AXIS_DIGESTS[axis_name]} vs 실제 {actual}. 술어·scope·scope_excluded·"
                "사각/오검 프로브를 바꾸려면 게이트와 테스트를 함께 고쳐야 합니다."
            )
    missing_digests = sorted(set(declared_axes) - set(AXIS_DIGESTS))
    if missing_digests:
        report.structural.append(
            f"측정 계약 지문이 없는 축이 있습니다: {missing_digests}. 지문 없는 축은 술어를 "
            "혼자 바꿀 수 있습니다."
        )

    # ── 분모 방어 ────────────────────────────────────────────────────────
    # 원장은 자기 주장의 크기를 스스로 줄일 수 없다. 축 이름 집합·계측 목록·판정 요구 목록·
    # 노드 행 하한을 **게이트가** 들고 대조한다.
    missing_axes = sorted(set(AXIS_FLOORS) - set(declared_axes))
    extra_axes = sorted(set(declared_axes) - set(AXIS_FLOORS))
    if missing_axes:
        report.structural.append(
            f"원장에서 축이 사라졌습니다: {missing_axes}. 분모는 원장이 아니라 게이트의 "
            "AXIS_FLOORS 가 듭니다 — 축을 줄이는 것은 계약 축소이고 사유와 함께 그쪽을 고쳐야 합니다."
        )
    if extra_axes:
        report.structural.append(
            f"게이트가 모르는 축이 원장에 있습니다: {extra_axes}. AXIS_FLOORS 에 하한을 "
            "등록하지 않은 축은 측정 하한 없이 사는 축입니다."
        )
    declared_metric_ids = {str(m.get("id")) for m in document.get("metric") or []}
    if declared_metric_ids != set(EXPECTED_METRIC_IDS):
        report.structural.append(
            "계측 항목 목록이 게이트의 EXPECTED_METRIC_IDS 와 다릅니다.\n"
            f"  원장에만: {sorted(declared_metric_ids - EXPECTED_METRIC_IDS)}\n"
            f"  게이트에만: {sorted(EXPECTED_METRIC_IDS - declared_metric_ids)}"
        )
    declared_review_ids = {str(i.get("id")) for i in document.get("review_item") or []}
    if declared_review_ids != set(EXPECTED_REVIEW_ITEM_IDS):
        report.structural.append(
            "판정 요구 항목 목록이 게이트의 EXPECTED_REVIEW_ITEM_IDS 와 다릅니다.\n"
            f"  원장에만: {sorted(declared_review_ids - EXPECTED_REVIEW_ITEM_IDS)}\n"
            f"  게이트에만: {sorted(EXPECTED_REVIEW_ITEM_IDS - declared_review_ids)}"
        )

    excluded_axes = list(document.get("excluded_axes") or [])
    declared_excluded = {str(e.get("axis")) for e in excluded_axes}
    if declared_excluded != set(EXPECTED_EXCLUDED_AXES):
        report.structural.append(
            "명시 제외 축 목록이 게이트의 EXPECTED_EXCLUDED_AXES 와 다릅니다 — 제외를 지우는 것은 "
            "「소리 나는 제외」를 조용한 유예로 되돌리는 것입니다.\n"
            f"  원장에만: {sorted(declared_excluded - set(EXPECTED_EXCLUDED_AXES))}\n"
            f"  게이트에만: {sorted(set(EXPECTED_EXCLUDED_AXES) - declared_excluded)}"
        )
    for excluded in excluded_axes:
        axis_name = str(excluded.get("axis", "<이름 없음>"))
        for field_name in ("axis", "reason", "owner"):
            if not excluded.get(field_name):
                report.structural.append(
                    f"제외 축 {axis_name}: `{field_name}` 이(가) 없습니다 — "
                    "조용한 유예가 아니라 소리 나는 제외여야 합니다."
                )
        # 제외 축이 **크기를 잴 수 있는 것**이면 그 크기를 든다. 「안 센다」와 「얼마나 안 세는지
        # 모른다」는 다르다 — 후자는 조용한 유예로 되돌아가는 길이다.
        if excluded.get("covers") is None:
            report.structural.append(
                f"제외 축 {axis_name}: `covers` 가 없습니다 — 제외가 제품 트리의 **어느 파일**을 "
                "설명하는지 적지 않으면 전수 피복이 성립하지 않습니다."
            )
        size = excluded.get("size")
        if size is None:
            if EXPECTED_EXCLUDED_AXES.get(axis_name):
                report.structural.append(
                    f"제외 축 {axis_name}: 게이트가 크기 프로브를 요구하는 제외인데 `size` 가 "
                    "없습니다 — 블록을 지우면 조용한 유예로 되돌아갑니다."
                )
            continue
        if not isinstance(size, dict) or size.get("current") is None:
            report.structural.append(f"제외 축 {axis_name}: `size` 는 `current` 를 든 표여야 합니다.")
            continue
        if not _require_predicate_triple(
            f"제외 축 {axis_name} 의 size",
            {
                "predicate": size.get("probe"),
                "scope": size.get("scope"),
                "scope_excluded": size.get("scope_excluded"),
                "unit": size.get("unit"),
            },
            report,
        ):
            continue
        try:
            found = _measure(
                repo, size["probe"], tuple(size["scope"]), None,
                tuple(size.get("scope_excluded") or ()),
            )
        except InventoryGateError as exc:
            report.structural.append(f"제외 축 {axis_name}: size 프로브 실패 — {exc}")
            continue
        if len(found) != int(size["current"]):
            report.structural.append(
                f"제외 축 {axis_name}: 제외한 표면이 움직였습니다 — 기록 {size['current']} → "
                f"실측 {len(found)}. 제외는 소리 나야 합니다."
            )
        # 크기를 **내용**으로만 재면 `export const probe = …` 만 든 모듈은 아무것도 보태지
        # 않아 숫자가 안 움직인다. 그런데 `covers` 가 그 글롭 전체를 전수 피복에서 면제하므로
        # 제외가 소리를 안 낸다. 파일 **수** 한 줄이 그 자리를 막는다.
        actual_files = len(repo.files(tuple(str(g) for g in excluded.get("covers") or ())))
        if size.get("files") is None:
            report.structural.append(
                f"제외 축 {axis_name}: `size.files` 가 없습니다 — 내용만 세면 셀 것 없는 "
                "모듈이 조용히 들어옵니다."
            )
        elif int(size["files"]) != actual_files:
            report.structural.append(
                f"제외 축 {axis_name}: 면제한 **파일 수**가 움직였습니다 — 기록 "
                f"{size['files']} → 실측 {actual_files}."
            )
    selected_axes = set(declared_axes) if axes is None else set(axes)
    unknown_axes = selected_axes - set(declared_axes)
    if unknown_axes:
        raise InventoryGateError(f"선언되지 않은 축을 골랐습니다: {sorted(unknown_axes)}")

    nodes = list(document.get("node") or [])
    report.node_rows = len(nodes)
    if len(nodes) < NODE_ROW_FLOOR:
        report.structural.append(
            f"노드 행이 {len(nodes)} 개로 하한 {NODE_ROW_FLOOR} 아래입니다 — 행을 지우면 폐포가 "
            "「측정 0 == 피복 0」으로 조용히 닫힙니다."
        )
    duplicate_ids = sorted(
        name for name, count in Counter(str(node.get("id")) for node in nodes).items() if count > 1
    )
    for name in duplicate_ids:
        report.structural.append(f"노드 id 가 중복입니다: {name}")

    for node in nodes:
        _check_node_shape(node, set(declared_axes), report)
        if node.get("axis") in selected_axes:
            _check_evidence(str(node.get("id")), node.get("evidence"), repo, report)
            if axes is None:
                _check_verification(str(node.get("id")), node.get("verification"), repo, report)

    axis_members: dict[str, list[str]] = {}
    for axis_name in sorted(selected_axes):
        decl = declared_axes[axis_name]
        if not _require_predicate_triple(f"축 {axis_name}", decl, report):
            continue
        try:
            measured = _measure(
                repo, decl["predicate"], tuple(decl["scope"]), None,
                tuple(decl.get("scope_excluded") or ()),
            )
        except InventoryGateError as exc:
            report.structural.append(f"축 {axis_name}: 재실측 실패 — {exc}")
            continue
        axis_members[axis_name] = measured
        _check_scope_limitation(axis_name, decl, report)
        floor = AXIS_FLOORS.get(axis_name)
        if floor is not None and len(measured) < floor:
            report.structural.append(
                f"축 {axis_name}: 측정 {len(measured)} 이 게이트 하한 {floor} 아래입니다 — "
                "술어나 scope 가 좁아졌는지 보세요. 하한을 낮추려면 사유와 함께 AXIS_FLOORS 를 "
                "고쳐야 하고 그 변경 자체가 리뷰 대상입니다."
            )
        axis_nodes = [node for node in nodes if node.get("axis") == axis_name]
        axis_report = _axis_coverage(axis_name, decl, axis_nodes, measured, repo)
        report.axes[axis_name] = axis_report
        _check_blind_spot(axis_name, decl, repo, axis_members, report, axis_report)

    if axes is None:
        _check_review_items(document, repo, report)
        _check_cross_axis_overlap(document, axis_members, report)

    declared_metrics = list(document.get("metric") or [])
    for metric in declared_metrics:
        if metrics is not None and str(metric.get("id")) not in metrics:
            continue
        _check_metric(metric, repo, axis_members, declared_axes, report)

    # 저장소 전수 scope 를 든 계측은 관측자 오염에 노출된다(다른 세션의 미커밋 변경이 값을
    # 바꾼다). 「오늘 0개」를 선언으로 두지 않고 실제 scope 를 읽어 대조한다.
    repo_wide: set[str] = set()
    for metric in declared_metrics:
        items = [metric, *(metric.get("aliases") or [])]
        for item in items:
            for pattern in item.get("scope") or []:
                if _REPO_WIDE_HEAD.search(str(pattern).split("/", 1)[0]):
                    repo_wide.add(str(metric.get("id")))
    declared_repo_wide = set(document.get("repo_wide_metrics") or [])
    if repo_wide != declared_repo_wide:
        report.structural.append(
            "`repo_wide_metrics` 가 실제 scope 와 다릅니다 — 저장소 전수 scope 계측은 고정 수치가 "
            "아니라 base_sha 앵커 + 정당화된 delta 로만 적을 수 있습니다.\n"
            f"  실측: {sorted(repo_wide)}\n  선언: {sorted(declared_repo_wide)}"
        )

    for rel in sorted(repo.decode_failures):
        report.structural.append(
            f"텍스트여야 하는 파일을 UTF-8 로 읽지 못했습니다: {rel} — 정규식 축이 이 파일을 "
            "조용히 건너뛰고 AST 축은 봅니다. 부재를 자동 감지해 스킵하지 않습니다."
        )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--report", choices=("text", "json"), default="text")
    parser.add_argument("--axis", action="append", dest="axes")
    # `--axis` 만 있으면 고른 축 밖을 가리키는 파생 계측이 전부 「재실측 실패」로 붉어
    # 음성 대조를 손으로 재현할 수 없다. 부분 실행은 전체 실행의 부분집합이 아니라
    # **다른 계약**이므로 두 선택자를 대칭으로 둔다.
    parser.add_argument("--metric", action="append", dest="metrics")
    # 지문은 손으로 못 쓴다 — 계약을 바꾼 사람이 이것을 돌려 게이트 상수를 갱신한다.
    parser.add_argument("--print-pins", action="store_true")
    args = parser.parse_args(argv)

    # 진단이 한국어라 콘솔 기본 코드페이지(cp949)에서는 실패 메시지 자체가 죽는다 —
    # 게이트가 좌표를 말하지 못하면 붉어도 쓸모가 없다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        document = load_document(args.document)
    except InventoryGateError as exc:
        print(f"게이트 전제가 깨졌습니다: {exc}", file=sys.stderr)
        return 2

    if args.print_pins:
        for name, decl in sorted((document.get("axes") or {}).items()):
            print(f'    "{name}": "{axis_measurement_digest(decl)}",')
        return 0

    try:
        report = check(
            document, args.repo_root.resolve(), axes=args.axes, metrics=args.metrics
        )
    except InventoryGateError as exc:
        print(f"게이트 전제가 깨졌습니다: {exc}", file=sys.stderr)
        return 2

    if args.report == "json":
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        for axis in report.axes.values():
            print(
                f"{axis.axis:26} 측정 {axis.measured:4}  피복 {axis.covered:4}  "
                f"미분류 {len(axis.unclassified):3}  유령 {len(axis.ghost):3}  "
                f"중복 {len(axis.duplicate):3}"
            )
        print(f"노드 행 {report.node_rows} · unknown 증거 {report.unknown_evidence}")
        for failure in report.failures:
            print(f"FAIL {failure}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
