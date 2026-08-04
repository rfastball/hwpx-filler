"""검증 책임 원장(``docs/react_verification_ledger.toml``)의 재실측기 + 음성 대조.

설계 정본은 #403 의 ``R-DESIGN-PACKET:v1`` rev3. 아래 질문들뿐이고 전부 비교 상대가 **저장소**다
— 게이트의 리터럴 사본과 대조하는 항목이 하나도 없다(2차의 「지어낸 SHA 를 자기 사본과 비교」가
났던 자리를 아예 만들지 않는다). 개수를 세지 않는 것이 계약이다: 세는 순간 그 수가 산문에
박히고, 질문을 하나 더할 때마다 산문이 먼저 거짓이 된다:

===  ====================================================================
G0   구조: 필수 필드가 차 있고 **모르는 키가 없는가**(``sucessor`` 오타 차단)
G1   파티션: ``자산 ∪ 제외 == 검증 트리`` 이고 교집합이 공집합인가
G2   제외의 순도: 제외 목록의 어떤 파일도 웹 표면에 **닿지** 않는가
G3   모든 ``file`` 이 **색인과 디스크 양쪽에** 실재하는가
G4   ``successor`` 가 ``keep`` 이 아닌 행의 후계가 **다른 자산 행**인가
G5   ``owner_stage`` 가 알려진 단계 어휘 안인가
G6   선언된 분모 밖 축이 **실재 파일을 가리키는가**(죽은 선언 차단)
G7   그 축이 **파티션과 겹치지 않는가**(자산을 분모 밖으로 미는 우회 차단)
G8   ``tests/`` 아래에 트리도 축도 아닌 **침묵한 파일이 없는가**(선언 집합의 전수성)
===  ====================================================================

**원장이 어떤 개수도 들지 않는다.** 2차 구현(#469)은 게이트의 테스트 개수가 원장의 값이라
음성 대조를 하나 더할 때마다 원장을 고쳐야 했고 그 회로가 폐기 사유였다. 이제 이 파일이
아무리 자라도 원장은 안 변한다.

**분모는 저장소가 든다.** 「자산 하한」 리터럴이 없어도 빈 원장은 통과할 수 없고(G1: ∅ ≠ 트리),
전량을 제외로 밀어 넣는 우회는 G2 가 막는다.

**술어는 여기 한 벌만 산다** — ``WEB_SURFACE``·``TREE_SPECS`` 의 사본이 원장에 없다. rev3
집필 중 같은 술어를 두 벌 쓰다 값이 갈린 실물 사고가 있었다(``selftest`` 누락).

이 파일의 G0·G2·G3·G4 형상은 전부 반증이 낸 것이다. 좁은 술어는 **헬퍼 경유 소비**와 **직접
DOM 조작**을 못 봤고, ``_read`` 는 디코드 실패를 「안 닿는다」와 같은 초록으로 보고했고, G3 는
색인만 봐서 디스크에서 지워진 파일을 통과시켰고, G4 는 **제외 항목**을 후계로 받았다. 전부
**책임을 조용히 사라지게 하는 길**이었고, 뿌리는 하나다 — 술어가 「무엇을 부르는가」만 보고
「무엇에 닿는가」를 안 봤다.

G6·G7 은 R1-99 독립 감사가 낸 것이고 **다른 층**을 연다. 앞의 것들이 파티션 *안쪽*을 지킨다면
이 둘은 **분모 자체**를 지킨다 — 트리가 안 보는 무리를 침묵으로 두면 「전수 피복」이 실제보다
넓게 읽힌다. 조치는 축을 트리로 끌어들이는 것이 아니라 **주장을 정직하게 좁히고 그 좁힘을
실행되는 술어로 만드는 것**이다(선언이 죽으면 G6 가, 선언이 자산을 삼키면 G7 이 문다).
같은 감사가 G2 도 다시 넓혔다: 헬퍼 이름 ``_web_artifact_contract`` 는 있는데 그것이 가리키는
**도메인 어휘**가 없어 봉인 산출물 소비자 둘이 제외에 앉아 있었다 — **집합 하나를 넓히고 그
형제를 안 넓힌 것**이다.

G8 은 그 다음 반증이 낸 것이고, 앞의 수정이 **같은 실수를 한 번 더** 했기 때문에 생겼다:
``tests/js/fixtures/`` 를 선언하면서 직계 형제 ``tests/fixtures/``·``tests/corpus/`` 를
빠뜨렸다(33건). 축을 손으로 열거하는 한 그 빠뜨림은 **기억의 문제**로 남으므로, ``tests/``
범위에 한해 **저장소가 답하게** 했다. 같은 반증이 음성 대조의 오조준도 잡았다 — ⑷ 를 겨눈다던
단언의 피해자가 ⑴ 에 이미 물려서, ⑷ 를 통째로 지워도 전부 초록이었다.
"""

from __future__ import annotations

import copy
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "react_verification_ledger.toml"

#: 검증 트리 = (접두 디렉터리, 허용 확장자). **분모를 드는 자리**라 원장이 아니라 여기 산다.
#: 글롭이 아니라 **접두 비교**다 — ``git ls-files 'scripts/*.py'`` 의 ``*`` 는 ``/`` 를 넘어서
#: (pathspec 은 fnmatch 다) 축을 조용히 넓히거나 좁힌다. 2차 패킷의 「스크립트 축이 비재귀라
#: ``scripts/live101/`` 6모듈이 축 밖」이 그 계열의 사고였다.
TREE_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tests", (".py",)),
    ("tests/js", (".test.js",)),
    ("scripts", (".py", ".mjs")),
)

#: 접두로 안 잡히는 단일 파일. 루트 ``conftest.py`` 는 CLAUDE.md 가 이름으로 부르는 홈 격리
#: 안전망인데 ``tests/`` 밑이 아니라 축 밖이었다.
TREE_EXTRA_FILES: tuple[str, ...] = ("conftest.py",)

#: 「이 파일이 웹 표면에 닿는가」의 **유일한** 술어. 네 갈래로 묻는다.
#:
#: ⑴ **제품 경로·전역을 이름으로 부른다** — 첫 줄.
#: ⑵ **헬퍼를 경유해 소비한다** — 둘째 줄. 이것이 없으면 술어가 규약을 지킬수록 눈이 먼다:
#:    ``tests/test_web_source_role.py`` 가 정적 테스트에게 물리 source 경로 재조립을
#:    **금지**하므로, 모범적인 웹 테스트일수록 ``frontend/`` 를 직접 안 쓴다. 좁은 판에서
#:    그런 파일 열이 제외에 앉아 있었다(실측).
#: ⑶ **DOM 을 직접 몬다** — 셋째 줄. 제품 경로 이름을 하나도 안 쓰고 웹 표면을 조작하는
#:    자리다. ``scripts/live101/{scenario,surface}.py`` 가 ``querySelector``·``dispatchEvent``
#:    ·``evaluate_js`` 로 실앱을 몰면서 제외에 앉아 있었다(실측).
#: ⑷ **봉인된 웹 산출물을 다룬다** — 넷째 줄. 프런트가 무엇으로 빌드되든 그 산출물의 정체성을
#:    재는 자리다. ⑵ 가 헬퍼 *이름* ``_web_artifact_contract`` 를 넣으면서 같은 것을 가리키는
#:    **도메인 어휘**를 안 넣어, ``scripts/verify_packaged_web.py`` (첫 줄이 "Compare the source
#:    Vite artifact with a PyInstaller bundled web tree") 와 ``tests/test_packaging_contract.py``
#:    가 제외에 앉아 있었다(R1-99 감사 실측). R2 가 빌드를 갈아 끼우면 정확히 이 축이 움직인다.
#:
#: 넷은 같은 결함의 네 변종이다 — **술어가 「무엇을 부르는가」만 보고 「무엇에 닿는가」를
#: 안 봤다.** ⑷ 는 그 위에 한 겹을 더 얹는다: **집합 하나를 넓히고 그 형제를 안 넓혔다**
#: (헬퍼 이름은 넣고 도메인 어휘는 안 넣었다). 넓히는 방향은 언제나 자유이므로 새 접촉
#: 방식이 보이면 여기에 더한다.
#: 네 갈래를 **이름 붙여 조립**한다. 사본을 뜨지 않으려는 것이다 — 음성 대조가 「이 피해자는
#: ⑷ 없이는 안 물린다」를 단언하려면 ⑴⑵⑶ 만 든 술어가 필요한데, 그것을 손으로 다시 적으면
#: 술어가 두 벌이 되고 값이 갈린다(rev3 집필 중 실제로 났던 사고다).
#:
#: ⑷ 의 주의 둘. **``web_artifact`` 가 ``resolve_web_artifact``·``_web_artifact_contract`` 를
#: 부분열로 포섭**하므로 그 둘을 ⑷ 에 따로 들지 않는다(들면 잉여이고 독립 항으로 읽힌다).
#: ``[Vv]ite`` 는 대소문자 둘 다 문다 — ``Vite`` 만 들면 ``vite.config`` 를 쓰는 파일이 조용히
#: 빠지고, R2 가 빌드를 갈아 끼울 때 움직이는 어휘가 정확히 소문자 쪽이다.
_SURFACE_NAMED = (
    r"frontend/|webapp|build/web|__hwpx|pywebview|WebFrontend|selftest|bridge\.js|index\.html"
)
_SURFACE_HELPER = r"_web_source|_press_probe|_web_artifact_contract"
_SURFACE_DOM = r"querySelector|getElementById|evaluate_js|dispatchEvent|window\.__cap"
_SURFACE_SEALED = r"web_artifact|artifact_id|tree_sha256|[Vv]ite"

WEB_SURFACE = re.compile(
    "|".join((_SURFACE_NAMED, _SURFACE_HELPER, _SURFACE_DOM, _SURFACE_SEALED))
)

#: ⑷ 를 뺀 술어. **음성 대조 전용**이고 게이트 판정에는 안 쓴다.
SURFACE_WITHOUT_SEALED = re.compile("|".join((_SURFACE_NAMED, _SURFACE_HELPER, _SURFACE_DOM)))

#: 인계선 어휘. 원장에서 유도하면 오타가 새 단계를 발명하므로 리터럴로 든다.
KNOWN_STAGES = frozenset(
    "R2-01 R2-02 R2-03 R2-04 R3-01 R3-02 R3-03 R4-01 R4-02 R4-03 R4-04 R5-01 R5-02 R5-03".split()
)

REQUIRED_ASSET_FIELDS = ("file", "responsibility", "owner_stage")

#: 자산 행이 들 수 있는 키의 **전부**. 모르는 키는 거절한다 — 이 저장소는 같은 이유로
#: ``webapp/action_registry.py`` 를 둔다(「오타난 키가 dict.get 으로 조용히 무시되지 않게」).
#: 여기서 그 결함은 특히 날카롭다: ``sucessor`` 로 오타 나면 행이 ``keep`` 으로 읽히고
#: R2~R4 의 인계 증거가 조용히 사라진다.
ALLOWED_ASSET_KEYS = frozenset({*REQUIRED_ASSET_FIELDS, "successor"})

#: 분모 밖 축의 키·매칭 어휘. 자산 행과 같은 이유로 모르는 키를 거절한다 — 여기서 오타가 나면
#: 「이만큼을 안 본다」는 선언이 조용히 아무것도 선언하지 않게 된다.
ALLOWED_AXIS_KEYS = frozenset({"id", "match", "reason", "owner_stage"})
AXIS_MATCH_KINDS = frozenset({"prefix", "root_suffix", "exact"})


# ---------------------------------------------------------------------------
# 저장소 관측
# ---------------------------------------------------------------------------


def _tracked_files() -> list[str]:
    """추적 파일 전량. ``git ls-files`` 는 UTF-8 로 디코드한다(Windows 기본 코드페이지 금지)."""
    raw = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [path for path in raw.split("\0") if path]


def _verification_tree(tracked: list[str]) -> set[str]:
    tree: set[str] = set()
    for prefix, suffixes in TREE_SPECS:
        for path in tracked:
            if path.startswith(prefix + "/") and path.endswith(suffixes):
                tree.add(path)
    tree.update(path for path in TREE_EXTRA_FILES if path in set(tracked))
    return tree


def _read(path: str) -> tuple[str, str | None]:
    """본문과 **읽기 실패 사유**를 함께 낸다.

    조용히 ``""`` 를 돌려주면 안 된다. 그 순간 G2 는 「웹 표면을 안 부른다」와 「못 읽었다」를
    같은 초록으로 보고한다 — cp949 로 저장된 파일이 ``frontend/js/app.js`` 를 통째로 담고도
    제외를 통과했다(실측). 디코드는 ``errors="replace"`` 로 절대 죽지 않게 하고, 진짜 못 읽는
    경우(부재·권한)는 **사유를 들고 올라와** 문제로 계상된다.
    """
    try:
        return (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return "", f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 질문들 — 각각 문제 목록을 낸다(빈 목록 = 통과). 개수는 안 센다(위 docstring 참조).
# ---------------------------------------------------------------------------


def _asset_files(document: dict[str, Any]) -> list[str]:
    return [str(row.get("file", "")) for row in document.get("asset", [])]


def _excluded_files(document: dict[str, Any]) -> list[str]:
    return [str(p) for p in document.get("out_of_scope", {}).get("files", [])]


def g1_partition(document: dict[str, Any], tree: set[str]) -> list[str]:
    """자산 ∪ 제외 == 트리, 교집합 ∅."""
    assets = _asset_files(document)
    excluded = _excluded_files(document)
    problems: list[str] = []

    for label, entries in (("자산", assets), ("제외", excluded)):
        seen: set[str] = set()
        for path in entries:
            if path in seen:
                problems.append(f"{label} 목록에 중복 행: {path}")
            seen.add(path)

    covered = set(assets) | set(excluded)
    for path in sorted(tree - covered):
        problems.append(f"검증 트리에 있으나 원장이 안 덮는다: {path}")
    for path in sorted(covered - tree):
        problems.append(f"원장에 있으나 검증 트리 밖이다: {path}")
    for path in sorted(set(assets) & set(excluded)):
        problems.append(f"자산과 제외에 동시에 있다: {path}")
    return problems


def g2_exclusion_purity(document: dict[str, Any]) -> list[str]:
    """제외 목록의 어떤 파일도 웹 표면을 이름으로 부르지 않는다.

    이것이 분모를 줄이는 유일한 경로를 막는다 — 넓히는 방향만 자유롭다.
    """
    problems: list[str] = []
    for path in _excluded_files(document):
        text, unreadable = _read(path)
        if unreadable is not None:
            problems.append(f"제외를 읽을 수 없어 판정 불가다: {path} ({unreadable})")
            continue
        found = WEB_SURFACE.search(text)
        if found:
            problems.append(f"제외인데 웹 표면에 닿는다: {path} ({found.group(0)!r})")
    return problems


def g3_files_exist(document: dict[str, Any], tracked: set[str]) -> list[str]:
    """색인과 디스크를 **둘 다** 묻는다.

    한쪽만 물으면 비대칭이 구멍이 된다 — G3 가 색인만 보고 G2 가 디스크만 읽으면, 추적된 채
    작업 트리에서 지워진 파일은 「실재한다」로 통과하면서 G2 에는 빈 본문으로 보인다.
    그 조합으로 웹 표면 자산을 제외로 강등하는 길이 열렸다(실측).
    """
    problems: list[str] = []
    for label, entries in (
        ("자산", _asset_files(document)),
        ("제외", _excluded_files(document)),
    ):
        for path in entries:
            if path not in tracked:
                problems.append(f"{label} 행이 추적되지 않는 파일을 가리킨다: {path}")
            elif not (REPO_ROOT / path).is_file():
                problems.append(f"{label} 행이 작업 트리에 없는 파일을 가리킨다: {path}")
    return problems


def g4_successors_exist(document: dict[str, Any]) -> list[str]:
    """``successor`` 는 기본값이 ``keep`` 이고, 그 밖의 값은 **다른 자산 행**이어야 한다.

    자산 행까지 요구하는 이유: 검증 책임의 후계는 그 자체로 검증 책임을 지는 자산이어야 한다.

    * 추적 여부만 물으면 ``README.md`` 가 통과한다.
    * **검증 트리 안**만 물어도 부족하다 — 트리는 자산과 제외의 합이라, ``tests/test_atomic.py``
      같은 **제외 항목**에 웹 검증 책임을 넘겼다고 주장할 수 있다. 제외는 「React 가 안
      건드린다」는 뜻이므로 그런 인계는 책임의 소멸과 구분되지 않는다.
    * 자기 자신도 안 된다 — 「옮겼다」가 아무것도 뜻하지 않게 된다.

    R1 에서 이 검사는 **휴면**이다(그런 행이 0). 그래서 살아 있다는 증거는 음성 대조뿐이다.
    """
    eligible = set(_asset_files(document))
    problems: list[str] = []
    for row in document.get("asset", []):
        successor = row.get("successor", "keep")
        if successor == "keep":
            continue
        if not isinstance(successor, str) or not successor.strip():
            problems.append(f"{row.get('file')}: successor 가 쓸 수 있는 문자열이 아니다")
            continue
        if successor == row.get("file"):
            problems.append(f"{row.get('file')}: 후계가 자기 자신이다")
        elif successor not in eligible:
            problems.append(f"{row.get('file')}: 후계가 자산 행이 아니다 -> {successor}")
    return problems


def g5_stage_vocabulary(document: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for row in document.get("asset", []):
        stage = row.get("owner_stage")
        if stage not in KNOWN_STAGES:
            problems.append(f"{row.get('file')}: 알 수 없는 owner_stage -> {stage!r}")
    return problems


def g0_structure(document: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if document.get("schema") != "react-verification-ledger/v1":
        problems.append(f"schema 가 예상과 다르다: {document.get('schema')!r}")
    for row in document.get("asset", []):
        for field in REQUIRED_ASSET_FIELDS:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{row.get('file')}: 필수 필드 {field} 가 비었다")
        for key in sorted(set(row) - ALLOWED_ASSET_KEYS):
            problems.append(f"{row.get('file')}: 모르는 키 {key!r} — 오타인가")
    if not str(document.get("out_of_scope", {}).get("reason", "")).strip():
        problems.append("out_of_scope.reason 이 비었다")
    problems.extend(_axis_structure(document))
    return problems


def _axis_structure(document: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for row in document.get("excluded_axis", []):
        axis_id = str(row.get("id", ""))
        if not axis_id.strip():
            problems.append("excluded_axis: id 가 비었다")
        elif axis_id in seen:
            problems.append(f"excluded_axis {axis_id!r}: id 가 중복이다")
        seen.add(axis_id)
        if not str(row.get("reason", "")).strip():
            problems.append(f"excluded_axis {axis_id!r}: reason 이 비었다")
        if row.get("owner_stage") not in KNOWN_STAGES:
            problems.append(
                f"excluded_axis {axis_id!r}: 알 수 없는 owner_stage -> {row.get('owner_stage')!r}"
            )
        for key in sorted(set(row) - ALLOWED_AXIS_KEYS):
            problems.append(f"excluded_axis {axis_id!r}: 모르는 키 {key!r} — 오타인가")
        match = row.get("match")
        if not isinstance(match, dict) or match.get("kind") not in AXIS_MATCH_KINDS:
            problems.append(f"excluded_axis {axis_id!r}: match.kind 가 어휘 밖이다 -> {match!r}")
    return problems


def _axis_members(row: dict[str, Any], tracked: list[str]) -> set[str]:
    """축이 **실제로 가리키는 추적 파일**. 선언이 아니라 저장소가 답한다."""
    match = row.get("match") or {}
    kind, value = match.get("kind"), match.get("value")
    if kind == "prefix":
        return {p for p in tracked if p.startswith(str(value))}
    if kind == "root_suffix":
        return {p for p in tracked if "/" not in p and p.endswith(str(value))}
    if kind == "exact":
        wanted = set(value or ())
        return {p for p in tracked if p in wanted}
    return set()


def g6_axes_are_live(document: dict[str, Any], tracked: list[str]) -> list[str]:
    """선언된 축이 **죽어 있지 않은가**.

    「분모가 이만큼을 안 본다」는 선언은 그 이만큼이 실재할 때만 정직하다. 경로가 개명되면
    선언은 조용히 아무것도 안 가리키게 되고, 그때 이 절은 **없는 사각을 사과하는 산문**이 된다.
    """
    problems: list[str] = []
    for row in document.get("excluded_axis", []):
        if not _axis_members(row, tracked):
            problems.append(f"excluded_axis {row.get('id')!r}: 가리키는 추적 파일이 0 이다")
    return problems


def g8_tests_tree_is_fully_accounted(
    document: dict[str, Any], tracked: list[str], tree: set[str]
) -> list[str]:
    """``tests/`` 아래 **모든** 추적 파일이 트리이거나 선언된 축인가.

    G6·G7 이 선언 하나하나의 건강을 본다면 이것은 **선언 집합이 전수인가**를 본다. 축을 손으로
    열거하는 한 「형제를 안 넓혔다」는 기억의 문제로 남고, 이 저장소는 그 결함류를 이미 여러 번
    밟았다 — 첫 판이 ``tests/js/fixtures/`` 를 선언하면서 직계 형제 ``tests/fixtures/``·
    ``tests/corpus/`` 를 빠뜨린 것이 가장 최근 표본이다(L16 실측 33건).

    그래서 여기서는 기억 대신 **저장소가 답한다**. 범위를 ``tests/`` 로 좁혀 적는 것은 정직을
    위해서다 — 저장소 전역의 폐포는 이 게이트가 지지 않는다(그 밖의 자료는 축이 이름으로 든다).
    """
    under_tests = {path for path in tracked if path.startswith("tests/")}
    declared: set[str] = set()
    for row in document.get("excluded_axis", []):
        declared |= _axis_members(row, tracked)
    orphans = sorted(under_tests - tree - declared)
    return [f"tests/ 아래인데 트리에도 선언된 축에도 없다: {path}" for path in orphans]


def g7_axes_stay_outside_the_partition(
    document: dict[str, Any], tracked: list[str], tree: set[str]
) -> list[str]:
    """축이 **파티션과 겹치지 않는가**.

    겹치면 같은 파일이 「행이 있다」와 「분모 밖이다」를 동시에 주장한다. G1 이 파티션 *안쪽*의
    폐포를 지킨다면 이것은 그 **바깥 경계**를 지킨다 — 축을 넓혀 자산을 분모 밖으로 밀어내는
    우회가 이 자리로 들어온다.
    """
    covered = tree | set(_asset_files(document)) | set(_excluded_files(document))
    problems: list[str] = []
    for row in document.get("excluded_axis", []):
        overlap = sorted(_axis_members(row, tracked) & covered)
        if overlap:
            problems.append(f"excluded_axis {row.get('id')!r}: 파티션과 겹친다 -> {overlap}")
    return problems


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    return _tracked_files()


@pytest.fixture(scope="module")
def tree(tracked: list[str]) -> set[str]:
    return _verification_tree(tracked)


@pytest.fixture(scope="module")
def ledger() -> dict[str, Any]:
    return tomllib.loads(LEDGER_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def mutable(ledger: dict[str, Any]) -> dict[str, Any]:
    """음성 대조용 사본. 변형은 **파싱된 문서의 한 좌표**만 건드린다.

    텍스트 전역 치환은 쓰지 않는다 — 전역 치환이 음성 대조 자신을 가린 전례가 있다.
    """
    return copy.deepcopy(ledger)


# ---------------------------------------------------------------------------
# 양성 — 오늘의 저장소에서 그 질문들이 전부 조용하다
# ---------------------------------------------------------------------------


def test_structure_is_well_formed(ledger: dict[str, Any]) -> None:
    assert g0_structure(ledger) == []


def test_g1_partition_closes(ledger: dict[str, Any], tree: set[str]) -> None:
    assert g1_partition(ledger, tree) == []


def test_g2_exclusions_are_pure(ledger: dict[str, Any]) -> None:
    assert g2_exclusion_purity(ledger) == []


def test_g3_every_row_points_at_a_real_file(ledger: dict[str, Any], tracked: list[str]) -> None:
    assert g3_files_exist(ledger, set(tracked)) == []


def test_g4_successors_resolve(ledger: dict[str, Any]) -> None:
    assert g4_successors_exist(ledger) == []


def test_g5_stages_are_known(ledger: dict[str, Any]) -> None:
    assert g5_stage_vocabulary(ledger) == []


def test_g6_declared_axes_point_at_real_files(
    ledger: dict[str, Any], tracked: list[str]
) -> None:
    assert g6_axes_are_live(ledger, tracked) == []


def test_g7_declared_axes_stay_outside_the_partition(
    ledger: dict[str, Any], tracked: list[str], tree: set[str]
) -> None:
    assert g7_axes_stay_outside_the_partition(ledger, tracked, tree) == []


def test_g8_tests_directory_has_no_silent_orphans(
    ledger: dict[str, Any], tracked: list[str], tree: set[str]
) -> None:
    assert g8_tests_tree_is_fully_accounted(ledger, tracked, tree) == []


def test_r1_moves_nothing_yet(ledger: dict[str, Any]) -> None:
    """전 행의 successor 가 기본값이다 — R2 가 **의도적으로** 깨는 자리이고 G4 가 받는다."""
    moved = [row["file"] for row in ledger["asset"] if row.get("successor", "keep") != "keep"]
    assert moved == [], f"R1 에서 옮겨진 자산이 있다: {moved}"


def _repo_is_shallow() -> bool:
    done = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip() == "true"


def test_baseline_sha_has_the_shape_of_a_commit(ledger: dict[str, Any]) -> None:
    """형식 층 — 얕은 클론에서도 답할 수 있는 질문이다.

    2차 라운드는 앞 일곱 자만 실재하는 SHA 를 실었고 게이트가 자기 리터럴 사본과 비교해
    통과시켰다. 지어낸 값과 그 사본은 언제나 같다. 그래서 사본 대조를 하지 않는다.
    """
    sha = ledger["baseline_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", sha), f"40자리 소문자 hex 가 아니다: {sha!r}"


def test_baseline_sha_is_a_real_ancestor(ledger: dict[str, Any]) -> None:
    """실재 **그리고 조상**인가 — 이력이 있을 때만 답할 수 있는 질문이다.

    ``cat-file -e`` 만으로는 부족하다. 그것은 존재 검사라 **곁가지 커밋도 통과**하고, 그러면
    기준선이 「이 파일들이 그 트리에 있었다」를 뜻하지 못한다(실측). 그래서 ``merge-base`` 다.

    **얕은 클론에서는 이 질문이 성립하지 않는다.** ``baseline_sha`` 는 정의상 HEAD 보다 앞선
    커밋이라 depth-1 클론에 **구조적으로** 없다. 조용히 통과시키면 초록이 「조상임을
    확인했다」로 읽히므로, 그러지 않고 사유를 들고 시끄럽게 실패한다.

    이 단언이 CI 에서 거짓 빨강이 되지 않는 이유는 답할 수 있게 **환경을 고쳤기** 때문이다 —
    ``quality.yml`` 의 ``pytest-contract`` 체크아웃이 ``fetch-depth: 0`` 을 받는다. 단언을
    깎아서 맞춘 것이 아니다.
    """
    sha = ledger["baseline_sha"]
    if _repo_is_shallow():
        pytest.fail(
            "얕은 클론이라 조상 여부를 물을 수 없다 — 환경 보고이지 제품 판정이 아니다. "
            "형식 층은 test_baseline_sha_has_the_shape_of_a_commit 가 진다. "
            "해소는 체크아웃의 fetch-depth: 0 (quality.yml 의 pytest-contract 는 이미 받는다).",
            pytrace=False,
        )
    resolved = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=REPO_ROOT)
    assert resolved.returncode == 0, f"저장소에 없는 커밋이다: {sha}"
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=REPO_ROOT)
    assert ancestry.returncode == 0, f"HEAD 의 조상이 아니다: {sha}"


# ---------------------------------------------------------------------------
# 프로브 생존 — 술어가 실제로 무는지 합성 입력으로 확인한다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "import x from 'frontend/js/app.js'",
        "from hwpxfiller.webapp import app",
        "sealed = Path('build/web')",
        "window.__hwpx.snapshot()",
        "import pywebview",
        "class WebFrontend:",
        "run the selftest probe",
        "see bridge.js for the port",
        "open index.html",
    ],
)
def test_web_surface_probe_actually_fires(sample: str) -> None:
    """잡아야 할 모양을 만들어 먹인다 — 프로브를 믿지 않는다.

    2차 라운드는 정규식 끝에 제어 문자(``0x08``)가 섞여 **어떤 입력에도 안 맞는 프로브를
    초록으로 실었다**. 눈에 안 보이고 초록이라 아무도 안 묻는다.
    """
    assert WEB_SURFACE.search(sample) is not None


def test_web_surface_probe_stays_quiet_on_unrelated_text() -> None:
    """거짓 양성도 본다 — 아무 글자에나 무는 술어는 제외를 전부 빨갛게 만든다."""
    assert WEB_SURFACE.search("순수 도메인 파서 테스트 — zipfile 과 lxml 만 쓴다") is None


def test_tree_enumeration_reaches_into_subdirectories(tree: set[str]) -> None:
    """접두 비교라 하위 디렉터리가 들어온다 — 글롭으로 돌아가면 이 단언이 먼저 죽는다."""
    nested = {path for path in tree if path.startswith("scripts/live101/")}
    assert nested, "scripts/live101/ 이 검증 트리에 하나도 안 들어왔다"


# ---------------------------------------------------------------------------
# 음성 대조 — 각 질문이 실제로 무는가
# ---------------------------------------------------------------------------


def test_n1_dropping_an_asset_row_breaks_the_partition(
    mutable: dict[str, Any], tree: set[str]
) -> None:
    dropped = mutable["asset"].pop(0)
    problems = g1_partition(mutable, tree)
    assert any(dropped["file"] in problem for problem in problems), problems


def test_n2_listing_a_file_on_both_sides_breaks_the_partition(
    mutable: dict[str, Any], tree: set[str]
) -> None:
    both = mutable["asset"][0]["file"]
    mutable["out_of_scope"]["files"].append(both)
    problems = g1_partition(mutable, tree)
    assert any("동시에" in problem and both in problem for problem in problems), problems


def test_n3_moving_a_web_facing_file_into_exclusions_is_caught(
    mutable: dict[str, Any],
) -> None:
    """**분모를 못 줄인다는 유일한 증거** — 옮겨도 파티션은 닫히고, 막는 것은 G2 하나다."""
    moved = mutable["asset"].pop(0)
    mutable["out_of_scope"]["files"].append(moved["file"])

    assert g1_partition(mutable, _verification_tree(_tracked_files())) == [], (
        "이 변형은 파티션을 깨지 않아야 한다 — 그래야 G2 가 유일한 방어선임이 증명된다"
    )
    problems = g2_exclusion_purity(mutable)
    assert any(moved["file"] in problem for problem in problems), problems


def test_n4_a_successor_that_does_not_exist_is_caught(mutable: dict[str, Any]) -> None:
    """휴면 검사(G4)가 살아 있다는 유일한 증거."""
    mutable["asset"][0]["successor"] = "tests/test_this_file_does_not_exist.py"
    problems = g4_successors_exist(mutable)
    assert any("자산 행이 아니다" in problem for problem in problems), problems


def test_n4b_a_successor_outside_the_verification_tree_is_caught(
    mutable: dict[str, Any],
) -> None:
    """추적되기만 하면 통과하던 자리 — 검증 책임의 후계는 검증 자산이어야 한다."""
    mutable["asset"][0]["successor"] = "README.md"
    problems = g4_successors_exist(mutable)
    assert any("README.md" in problem for problem in problems), problems


def test_n4c_a_successor_pointing_at_itself_is_caught(mutable: dict[str, Any]) -> None:
    """자기 자신을 후계로 적으면 「옮겼다」가 아무것도 뜻하지 않는다."""
    row = mutable["asset"][0]
    row["successor"] = row["file"]
    problems = g4_successors_exist(mutable)
    assert any("자기 자신" in problem for problem in problems), problems


def test_n4e_a_successor_that_is_an_excluded_file_is_caught(
    mutable: dict[str, Any],
) -> None:
    """**검증 트리 안**만 물으면 뚫리던 자리.

    트리는 자산과 제외의 합이다. 그래서 제외 항목을 후계로 적으면 「웹 검증 책임을 넘겼다」는
    주장이 통과했는데, 제외의 뜻은 「React 가 안 건드린다」이므로 그 인계는 책임의 소멸과
    구분되지 않는다. 후계는 **자산 행**이어야 한다.
    """
    excluded = mutable["out_of_scope"]["files"][0]
    mutable["asset"][0]["successor"] = excluded
    problems = g4_successors_exist(mutable)
    assert any(excluded in problem for problem in problems), problems


def test_n4f_a_dom_driving_file_cannot_sit_in_exclusions(mutable: dict[str, Any]) -> None:
    """제품 경로 이름을 하나도 안 쓰고 **DOM 을 직접 모는** 파일도 제외에 못 앉는다.

    ``scripts/live101/{scenario,surface}.py`` 가 실제로 그 상태였다 — ``querySelector`` ·
    ``dispatchEvent`` · ``evaluate_js`` 로 실앱을 몰면서 제외 목록에 있었다.
    """
    driver = "scripts/live101/surface.py"
    mutable["asset"] = [row for row in mutable["asset"] if row["file"] != driver]
    mutable["out_of_scope"]["files"] = [*mutable["out_of_scope"]["files"], driver]
    problems = g2_exclusion_purity(mutable)
    assert any(driver in problem for problem in problems), problems


def test_n4d_a_typo_in_the_successor_key_is_caught(mutable: dict[str, Any]) -> None:
    """``sucessor`` 오타는 행을 조용히 ``keep`` 으로 읽게 만든다 — G4 는 쳐다보지도 않는다.

    이 저장소가 ``webapp/action_registry.py`` 를 두는 이유와 같은 결함류이고, 하필
    R2~R4 의 인계 증거를 나르는 필드에서 난다.
    """
    mutable["asset"][0]["sucessor"] = "tests/test_web_dom_contract.py"
    problems = g0_structure(mutable)
    assert any("sucessor" in problem for problem in problems), problems


def test_n5_a_ghost_file_path_is_caught(mutable: dict[str, Any], tracked: list[str]) -> None:
    mutable["asset"][0]["file"] = "tests/test_ghost.py"
    problems = g3_files_exist(mutable, set(tracked))
    assert any("tests/test_ghost.py" in problem for problem in problems), problems


def test_n5b_a_tracked_file_missing_from_the_worktree_is_caught(
    mutable: dict[str, Any], tracked: list[str]
) -> None:
    """색인에는 있고 디스크에는 없는 상태.

    이 자리를 안 물으면 G2 가 그 파일을 **빈 본문**으로 읽어 「웹 표면에 안 닿는다」로
    보고한다. 그 조합이 웹 표면 자산을 제외로 강등하는 길이었다(실측). 여기서는 저장소를
    건드리지 않고 색인 목록에만 유령을 더해 같은 형상을 만든다.
    """
    ghost = "tests/test_absent_from_worktree.py"
    mutable["asset"][0]["file"] = ghost
    problems = g3_files_exist(mutable, set(tracked) | {ghost})
    assert any("작업 트리에 없는" in problem and ghost in problem for problem in problems), problems


def test_n5c_an_undecodable_exclusion_is_reported_not_silently_empty(
    mutable: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """읽기 실패를 「웹 표면에 안 닿는다」와 같은 초록으로 보고하지 않는다.

    ``_read`` 가 예전에 ``UnicodeDecodeError`` 를 삼키고 ``""`` 를 돌려줬다. 그때 cp949 로
    저장된 파일이 ``frontend/js/app.js`` 를 통째로 담고도 제외를 통과했다. 지금은 디코드가
    ``errors="replace"`` 라 그 본문이 **읽히고**, 진짜 못 읽는 경우만 사유로 올라온다.
    """
    cp949_file = tmp_path / "legacy_encoded.py"
    cp949_file.write_bytes("# 프런트엔드: frontend/js/app.js 를 읽는다\n".encode("cp949"))
    monkeypatch.setattr("test_react_verification_ledger.REPO_ROOT", tmp_path, raising=True)
    mutable["out_of_scope"]["files"] = ["legacy_encoded.py"]
    problems = g2_exclusion_purity(mutable)
    assert any("legacy_encoded.py" in problem for problem in problems), problems


def test_n6_an_invented_stage_is_caught(mutable: dict[str, Any]) -> None:
    mutable["asset"][0]["owner_stage"] = "R9-99"
    problems = g5_stage_vocabulary(mutable)
    assert any("R9-99" in problem for problem in problems), problems


def test_n7_an_empty_ledger_cannot_pass(tree: set[str]) -> None:
    """극단 — 빈 원장. 하한 리터럴 없이도 막힌다, 분모를 저장소가 들기 때문에."""
    empty: dict[str, Any] = {
        "schema": "react-verification-ledger/v1",
        "asset": [],
        "out_of_scope": {"reason": "x", "files": []},
    }
    assert g1_partition(empty, tree) != []


def test_n8_sweeping_everything_into_exclusions_cannot_pass(tree: set[str]) -> None:
    """극단 — 자산 0, 전량 제외. G1 은 통과하고 G2 가 막는다."""
    swept: dict[str, Any] = {
        "schema": "react-verification-ledger/v1",
        "asset": [],
        "out_of_scope": {"reason": "x", "files": sorted(tree)},
    }
    assert g1_partition(swept, tree) == [], "파티션은 닫혀야 한다 — G2 가 유일한 방어선"
    assert g2_exclusion_purity(swept) != []


def test_n9_a_blank_required_field_is_caught(mutable: dict[str, Any]) -> None:
    mutable["asset"][0]["responsibility"] = "   "
    problems = g0_structure(mutable)
    assert any("responsibility" in problem for problem in problems), problems


def test_n10_a_duplicated_asset_row_is_caught(mutable: dict[str, Any], tree: set[str]) -> None:
    mutable["asset"].append(copy.deepcopy(mutable["asset"][0]))
    problems = g1_partition(mutable, tree)
    assert any("중복" in problem for problem in problems), problems


#: ⑷ 의 어휘로**만** 물리는 실물 둘. 피해자를 이렇게 고르는 것이 이 음성 대조의 전부다 —
#: 첫 판은 ``scripts/seal_web_artifact.py`` 를 썼는데 그 파일은 ⑴ 의 ``build/web`` 에 이미
#: 물려서, **⑷ 를 통째로 지워도 초록이었다**(L16 실측: S1 전체 revert 에 43 passed). 방어한다고
#: 세운 단언이 아무것도 안 지키는 상태였고, 그것이 이 원장이 겨누는 결함 그 자체다.
#: 둘은 ⑷ 의 **서로 다른 어휘**로 물리므로 어느 쪽을 지워도 최소 하나가 빨개진다.
SEALED_ONLY_VICTIMS = (
    ("tests/test_packaging_contract.py", "web_artifact"),
    ("scripts/verify_packaged_web.py", "ite"),
)


@pytest.mark.parametrize(("victim", "term"), SEALED_ONLY_VICTIMS)
def test_n11_a_sealed_artifact_consumer_cannot_sit_in_exclusions(
    mutable: dict[str, Any], victim: str, term: str
) -> None:
    """봉인 산출물을 다루는 파일이 제외에 앉으면 문다 — R1-99 가 잡은 그 자리다.

    변형은 최소로: 이미 자산인 한 행을 **제외로 옮긴다**. 합성 문자열이 아니라 저장소의
    실물이라 술어가 실재를 무는지 그대로 답한다. 첫 단언이 **피해자 자격**을 먼저 확인한다 —
    그것이 없으면 이 대조는 자기가 겨눈다고 적은 것을 안 겨눈 채 초록일 수 있다.
    """
    assert not SURFACE_WITHOUT_SEALED.search(
        (REPO_ROOT / victim).read_text(encoding="utf-8", errors="replace")
    ), f"{victim} 이 ⑷ 이전 어휘에도 물린다 — 이 음성 대조는 ⑷ 를 안 지킨다"
    mutable["asset"] = [row for row in mutable["asset"] if row["file"] != victim]
    mutable["out_of_scope"]["files"] = sorted([*mutable["out_of_scope"]["files"], victim])
    problems = g2_exclusion_purity(mutable)
    assert any(victim in problem and term in problem for problem in problems), problems


def test_n15_dropping_a_declared_axis_reopens_the_silence(
    mutable: dict[str, Any], tracked: list[str], tree: set[str]
) -> None:
    """축 선언을 빼면 그만큼이 **다시 침묵**이 되고 G8 이 그것을 운다.

    첫 판에는 축 집합 자체를 지키는 단언이 없어 선언을 통째로 지워도 초록이었다(L16 실측).
    이제 ``tests/`` 범위에 한해 그 삭제가 소리를 낸다.
    """
    victim = "js-negative-fixtures"
    mutable["excluded_axis"] = [
        row for row in mutable["excluded_axis"] if row.get("id") != victim
    ]
    problems = g8_tests_tree_is_fully_accounted(mutable, tracked, tree)
    assert any("tests/js/fixtures/" in problem for problem in problems), problems


def test_n12_a_dead_axis_declaration_is_caught(
    mutable: dict[str, Any], tracked: list[str]
) -> None:
    """가리키는 것이 없어진 축 선언은 **사각의 사과가 아니라 거짓말**이 된다."""
    mutable["excluded_axis"][0]["match"] = {"kind": "prefix", "value": "이-경로는-없다/"}
    problems = g6_axes_are_live(mutable, tracked)
    assert any("0 이다" in problem for problem in problems), problems


def test_n13_an_axis_that_swallows_the_partition_is_caught(
    mutable: dict[str, Any], tracked: list[str], tree: set[str]
) -> None:
    """축을 넓혀 자산을 분모 밖으로 밀어내는 우회를 막는다."""
    mutable["excluded_axis"][0]["match"] = {"kind": "prefix", "value": "tests/"}
    problems = g7_axes_stay_outside_the_partition(mutable, tracked, tree)
    assert any("겹친다" in problem for problem in problems), problems


def test_n14_a_typo_in_an_axis_key_is_caught(mutable: dict[str, Any]) -> None:
    """``sucessor`` 오타가 행을 조용히 삼킨 전례와 같은 이유로 축에서도 모르는 키를 거절한다."""
    mutable["excluded_axis"][0]["resaon"] = mutable["excluded_axis"][0].pop("reason")
    problems = g0_structure(mutable)
    assert any("resaon" in problem for problem in problems), problems
    assert any("reason 이 비었다" in problem for problem in problems), problems
