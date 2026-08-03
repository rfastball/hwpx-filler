"""검증 책임 원장(``docs/react_verification_ledger.toml``)의 재실측기 + 음성 대조.

설계 정본은 #403 의 ``R-DESIGN-PACKET:v1`` rev3. 다섯 질문뿐이고 전부 비교 상대가 **저장소**다
— 게이트의 리터럴 사본과 대조하는 항목이 하나도 없다(2차의 「지어낸 SHA 를 자기 사본과 비교」가
났던 자리를 아예 만들지 않는다):

===  ====================================================================
G0   구조: 필수 필드가 차 있고 **모르는 키가 없는가**(``sucessor`` 오타 차단)
G1   파티션: ``자산 ∪ 제외 == 검증 트리`` 이고 교집합이 공집합인가
G2   제외의 순도: 제외 목록의 어떤 파일도 웹 표면에 **닿지** 않는가
G3   모든 ``file`` 이 **색인과 디스크 양쪽에** 실재하는가
G4   ``successor`` 가 ``keep`` 이 아닌 행의 후계가 **검증 트리 안에** 있는가
G5   ``owner_stage`` 가 알려진 단계 어휘 안인가
===  ====================================================================

**원장이 어떤 개수도 들지 않는다.** 2차 구현(#469)은 게이트의 테스트 개수가 원장의 값이라
음성 대조를 하나 더할 때마다 원장을 고쳐야 했고 그 회로가 폐기 사유였다. 이제 이 파일이
아무리 자라도 원장은 안 변한다.

**분모는 저장소가 든다.** 「자산 하한」 리터럴이 없어도 빈 원장은 통과할 수 없고(G1: ∅ ≠ 트리),
전량을 제외로 밀어 넣는 우회는 G2 가 막는다.

**술어는 여기 한 벌만 산다** — ``WEB_SURFACE``·``TREE_SPECS`` 의 사본이 원장에 없다. rev3
집필 중 같은 술어를 두 벌 쓰다 값이 갈린 실물 사고가 있었다(``selftest`` 누락).

이 파일의 G2·G3·G4·G0 형상은 반증 왕복이 낸 것이다. 좁은 술어는 **헬퍼 경유 소비**를 못 봤고,
``_read`` 는 디코드 실패를 「안 닿는다」와 같은 초록으로 보고했고, G3 는 색인만 봐서 디스크에서
지워진 파일을 통과시켰다. 셋 다 **자산을 제외로 강등하는 길**이었다.
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

#: 「이 파일이 웹 표면에 닿는가」의 **유일한** 술어.
#:
#: 뒤쪽 세 이름이 **헬퍼 경유 소비**를 잡는다. 이것이 없으면 술어가 규약을 지킬수록 눈이 먼다 —
#: ``tests/test_web_source_role.py`` 가 정적 테스트에게 물리 source 경로 재조립을 **금지**하므로,
#: 모범적인 웹 테스트일수록 ``frontend/`` 를 직접 안 쓰고 ``_web_source`` 를 통해 읽는다.
#: 좁은 판으로는 그런 파일 10개가 제외에 영영 앉아 있을 수 있었다(실측).
WEB_SURFACE = re.compile(
    r"frontend/|webapp|build/web|__hwpx|pywebview|WebFrontend|selftest|bridge\.js"
    r"|index\.html|_web_source|_press_probe|_web_artifact_contract"
)

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
# 다섯 질문 — 각각 문제 목록을 낸다(빈 목록 = 통과)
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


def g4_successors_exist(document: dict[str, Any], tree: set[str]) -> list[str]:
    """``successor`` 는 기본값이 ``keep`` 이고, 그 밖의 값은 **검증 트리 안**이어야 한다.

    트리 안까지 요구하는 이유: 검증 책임의 후계는 검증 자산이어야 한다. 추적 여부만 물으면
    ``README.md`` 나 **자기 자신**이 후계로 통과한다(실측).

    R1 에서 이 검사는 **휴면**이다(그런 행이 0). 그래서 살아 있다는 증거는 음성 대조뿐이다.
    """
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
        elif successor not in tree:
            problems.append(f"{row.get('file')}: 후계가 검증 트리 안에 없다 -> {successor}")
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
# 양성 — 오늘의 저장소에서 다섯 질문이 전부 조용하다
# ---------------------------------------------------------------------------


def test_structure_is_well_formed(ledger: dict[str, Any]) -> None:
    assert g0_structure(ledger) == []


def test_g1_partition_closes(ledger: dict[str, Any], tree: set[str]) -> None:
    assert g1_partition(ledger, tree) == []


def test_g2_exclusions_are_pure(ledger: dict[str, Any]) -> None:
    assert g2_exclusion_purity(ledger) == []


def test_g3_every_row_points_at_a_real_file(ledger: dict[str, Any], tracked: list[str]) -> None:
    assert g3_files_exist(ledger, set(tracked)) == []


def test_g4_successors_resolve(ledger: dict[str, Any], tree: set[str]) -> None:
    assert g4_successors_exist(ledger, tree) == []


def test_g5_stages_are_known(ledger: dict[str, Any]) -> None:
    assert g5_stage_vocabulary(ledger) == []


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


def test_n4_a_successor_that_does_not_exist_is_caught(
    mutable: dict[str, Any], tree: set[str]
) -> None:
    """휴면 검사(G4)가 살아 있다는 유일한 증거."""
    mutable["asset"][0]["successor"] = "tests/test_this_file_does_not_exist.py"
    problems = g4_successors_exist(mutable, tree)
    assert any("검증 트리 안에 없다" in problem for problem in problems), problems


def test_n4b_a_successor_outside_the_verification_tree_is_caught(
    mutable: dict[str, Any], tree: set[str]
) -> None:
    """추적되기만 하면 통과하던 자리 — 검증 책임의 후계는 검증 자산이어야 한다."""
    mutable["asset"][0]["successor"] = "README.md"
    problems = g4_successors_exist(mutable, tree)
    assert any("README.md" in problem for problem in problems), problems


def test_n4c_a_successor_pointing_at_itself_is_caught(
    mutable: dict[str, Any], tree: set[str]
) -> None:
    """자기 자신을 후계로 적으면 「옮겼다」가 아무것도 뜻하지 않는다."""
    row = mutable["asset"][0]
    row["successor"] = row["file"]
    problems = g4_successors_exist(mutable, tree)
    assert any("자기 자신" in problem for problem in problems), problems


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
