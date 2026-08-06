"""React 소유권 인벤토리 원장의 폐포 게이트 + **판별력의 음성 대조**.

## 두 겹인 이유

「미분류 0」을 단언하는 테스트는 **추출기가 아무것도 못 볼 때도** 초록이다. 축이 빈 목록을
내면 M 도 C 도 공집합이고 폐포는 닫힌다. 그래서 양성 단언(실 저장소에서 초록)만으로는
이 게이트가 살아 있는지 알 수 없다.

아래 음성 대조 열다섯이 그 판별력을 매번 증명한다. 방향이 둘이다:

* **저장소 변이 6**(N1·N1b·N2·N3·N4·N5) — 원장을 한 글자도 안 건드리고 **복제 트리의 코드**를
  한 좌표 바꾼다. 이 게이트가 실제로 막아야 하는 실패가 「코드가 늘고 원장이 안 느는 것」이라
  음성 대조의 절반이 이쪽이어야 한다.
* **원장 변이 9**(N6~N14) — 저장소를 한 글자도 안 건드리고 **파싱된 문서**를 한 좌표 바꾼다.
  텍스트 전역 치환은 쓰지 않는다 — 전역 치환이 음성 대조 자신을 가린 전례가 이 저장소에 있다.

각 케이스는 red 가 나는 것만이 아니라 **실패 메시지가 그 좌표를 이름으로 말하는지**까지
단언한다. 좌표를 못 말하는 red 는 다음 사람에게 아무것도 주지 않는다.

## 부분 실행은 전체 실행의 부분집합이 **아니다**

``check(..., axes=[…])`` 는 고른 축만 재고 `verification` 실재 확인과 판정 요구 항목 검사를
끈다. 음성 대조가 부분 트리를 쓰려면 그 선택자가 필요하지만, 그래서 **부분 실행에서 초록인
것이 전체 실행에서도 초록이라는 뜻이 아니다**. 전체 실행만 겨누는 대조는 아래에서 `axes=None`
으로 따로 세운다.

## 먼저 인정하는 것

이 슬라이스는 **실재 유령으로 red 를 낼 수 없다**. 원장과 게이트가 같은 PR 에서 태어나므로
병합 시점의 원장은 정의상 완전하고 그때 게이트는 반드시 초록이다. 유령 대조(N10)는 원장 변이다.
그리고 `M − C = ∅` 은 저장소에 대해서가 아니라 **선언된 축의 추출기가 본 것**에 대해 0이다 —
그 문장은 원장의 `scope_statement` 에 데이터로 들어 있다.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from _web_source import SOURCE_ROOT

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = REPO_ROOT / "scripts" / "check_react_ownership_inventory.py"
LEDGER_PATH = REPO_ROOT / "docs" / "react_ownership_inventory.toml"


def _load_gate():
    """게이트 스크립트를 모듈로 싣는다.

    ``sys.modules`` 등록이 **구현 계약**이다 — 등록하지 않으면 스크립트 안의 ``@dataclass``가
    자기 모듈을 못 찾아 import 단계에서 죽는다. R1-99 감사자가 스크립트를 단독 실행하는 경로와
    같은 자리를 여기서 미리 밟는다.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    spec = importlib.util.spec_from_file_location("check_react_ownership_inventory", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return gate.load_document(LEDGER_PATH)


@pytest.fixture
def mutable_document(document: dict[str, Any]) -> dict[str, Any]:
    """문서의 깊은 사본 — 원장 변이는 **파싱된 dict** 한 좌표만 바꾼다."""
    return copy.deepcopy(document)


@pytest.fixture
def frontend_tree(tmp_path: Path) -> Path:
    """복제 트리의 **저장소 루트** — 정적 자산 파일 수 계약까지 그대로 복제한다.

    저장소 변이는 실 저장소를 절대 건드리지 않는다. `axes=[…]` 인자로 해당 축만 검사해
    없는 파일 때문에 무관한 축이 죽지 않게 한다 — 그 인자가 필요한 이유가 여기다.

    물리 경로 이름은 :mod:`_web_source` 가 단일 출처다 — 여기서 다시 조립하면 소스 트리를
    옮기는 날 이 게이트만 옛 자리를 보며 조용히 산다.
    """
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copytree(SOURCE_ROOT, root / SOURCE_ROOT.name)
    return root


@pytest.fixture
def clone_source(frontend_tree: Path) -> Path:
    """복제 트리 안의 정적 소스 루트."""
    return frontend_tree / SOURCE_ROOT.name


def _failures(report) -> str:
    return "\n".join(report.failures)


# ──────────────────────────────────────────────────────────────────────────
# 양성 — 실 저장소에서 폐포가 닫힌다
# ──────────────────────────────────────────────────────────────────────────


def test_inventory_is_closed_over_the_repository(document: dict[str, Any]) -> None:
    """선언된 축 전부에 대해 미분류·유령·중복·멤버수·사각이 전부 0이어야 한다."""
    report = gate.check(document, REPO_ROOT)
    assert report.ok, "소유권 원장이 저장소와 어긋납니다.\n" + _failures(report)


def test_every_declared_axis_actually_measures_something(document: dict[str, Any]) -> None:
    """빈 추출기는 폐포를 **초록으로** 닫는다 — 축마다 측정이 0이 아님을 따로 센다."""
    report = gate.check(document, REPO_ROOT)
    empty = sorted(name for name, axis in report.axes.items() if axis.measured == 0)
    assert not empty, f"측정이 0인 축이 있습니다(추출기가 아무것도 못 봤을 수 있습니다): {empty}"
    # `set(report.axes) == set(document["axes"])` 는 **자기참조**라 빈 원장에서도 참이었다.
    # 분모는 게이트가 든 계약과 대조한다.
    assert set(report.axes) == set(EXPECTED_AXIS_CONTRACT), (
        "측정한 축이 게이트·테스트가 든 계약과 다릅니다."
    )


#: **분모의 세 번째 자리.** 원장이 측정 계약을 들고, 게이트가 하한과 지문을 들고, 이 리터럴이
#: 그 상수 자체를 든다. 이름 집합만 두면 **값**은 여전히 1파일 앵커라 하한을 전부 1로 낮춰도
#: 조용했다 — 그래서 이름이 아니라 `(하한, 지문)` 쌍을 든다. 축의 측정 계약을 바꾸려면
#: 원장·게이트·이 표 **셋**이 함께 움직이고 그 diff 가 리뷰 표면에 뜬다.
EXPECTED_AXIS_CONTRACT: dict[str, tuple[int, str]] = {
    # R4-02 재고정 — 이관이 끝난 축은 legacy 생산 자리가 사라지며 분모가 준다. 하한을
    # 함께 내리지 않으면 게이트가 이관 자체를 빨강으로 보고, 그 빨강을 피하려 legacy
    # 잔재를 남기는 압력이 생긴다(게이트 AXIS_FLOORS 주석에 같은 사유가 있다).
    "dom_data_attr": (4, "e0bd6cb1822fd50fefbda2c3fac621d5"),
    "dom_js_data_attr": (80, "d6c24f47a9f809b5e6f63ddd2b09e372"),
    "dom_js_site": (120, "7ce48e5d41ae530e66a2156e113bb0bb"),
    "dom_static": (93, "a0de506720a9704065dde2bf17410d50"),
    "lifecycle_factory": (54, "f774587af230cf5222697cd0f0e0a050"),
    "lifecycle_hook": (6, "1f090f972ecaf5c9e0a54796c6849437"),
    "state_js_module": (65, "fef89b77255e04f0cf05d4b19e09c733"),
    "state_ring1": (10, "9742c77daae0c11112e40c009a5b23c6"),
    "state_snapshot_channel": (6, "5891957f0ed54565587e17c150eed087"),
    # #491 재고정 — TS/TSX 감산형 scope로 R2 runtime·R3 overlay/shell attach/release가 편입됐다.
    "subscription_listener": (40, "8064cf796b67e47a094e61c7362e4b5b"),
    # R4-02 — 축 단위가 「화면이 구독한다」에서 「기반이 탭을 세우고 화면은 model 을
    # 구독한다」로 바뀌었다. 술어에 `.subscribe(` 가 붙고 scope 가 React 트리로 갔다.
    "subscription_push": (6, "6b30b15e7ca10851763bd0ec96b48725"),
    "subscription_release": (15, "08fce41a56c1108632cb8bfd7364912c"),
}


def test_axis_contract_is_anchored_outside_the_gate() -> None:
    """하한의 **값**과 술어의 **지문**까지 두 자리에서 못박는다.

    이름 집합만 대조하던 판은 하한 열한 개를 전부 1로 낮춰도 초록이었다 — 「이 리터럴이 그
    상수가 조용히 줄어드는 것을 막는다」가 값에 대해서는 거짓이었다.
    """
    actual = {
        name: (floor, gate.AXIS_DIGESTS.get(name, "<지문 없음>"))
        for name, floor in gate.AXIS_FLOORS.items()
    }
    assert actual == EXPECTED_AXIS_CONTRACT, (
        "게이트의 (하한, 측정 계약 지문) 과 이 파일의 EXPECTED_AXIS_CONTRACT 가 다릅니다.\n"
        f"  게이트: {sorted(actual.items())}\n"
        f"  기대:   {sorted(EXPECTED_AXIS_CONTRACT.items())}"
    )


def test_r4_handoff_row_allocation_is_exact(document: dict[str, Any]) -> None:
    """rev8 중앙 판정의 R4 69행 배분은 단계 사이에서 조용히 이동할 수 없다."""
    actual = Counter(
        node["handoff_slice"]
        for node in document["node"]
        if str(node.get("handoff_slice", "")).startswith("R4-")
    )
    assert actual == {
        "R4-01 #414": 28,
        "R4-02 #415": 25,
        "R4-03 #416": 15,
        "R4-04 #417": 1,
    }
    assert sum(actual.values()) == 69


def test_r4_job_split_and_landed_static_shell_are_explicit(
    document: dict[str, Any],
) -> None:
    """job read/run 경계와 R4-01이 비운 정적 subtree를 행 이름·selector로 고정한다."""
    nodes = {node["id"]: node for node in document["node"]}
    assert {
        "dom/job/jobDataGrid-shell",
        "dom/job/jobPreflight",
        "dom/job/jobSideCard-read",
        "dom/job/jobSideCard-run",
        "dom-js-data/job-read",
        "dom-js-data/job-run",
    } <= nodes.keys()
    assert {
        "dom/job/jobDataGrid",
        "dom/job/jobSideCard",
        "dom-js-data/job",
    }.isdisjoint(nodes)

    expected_subtrees = {
        "dom/scr-library": ("scr-library", 0),
        "dom/job/jobDataGrid-shell": ("jobDataGrid", 5),
        "dom/job/jobSideCard-read": ("jobSideCard", 2),
        "dom/overlay/poolRegModal": ("poolRegModal", 0),
        "dom/overlay/dataPickerModal": ("dataPickerModal", 0),
        "dom/overlay/libraryMoveModal": ("libraryMoveModal", 0),
        "dom/overlay/jobBrowseSheet": ("jobBrowseSheet", 0),
    }
    for node_id, (root, count) in expected_subtrees.items():
        assert nodes[node_id]["selector"] == {
            "kind": "subtree",
            "root": root,
            "members_expected": count,
        }

    assert nodes["dom/job/jobPreflight"]["handoff_slice"] == "R4-03 #416"
    assert nodes["dom/job/jobSideCard-run"]["handoff_slice"] == "R4-03 #416"
    assert nodes["dom-js-data/job-read"]["handoff_slice"] == "R4-01 #414"
    assert nodes["dom-js-data/job-run"]["handoff_slice"] == "R4-03 #416"


def test_product_tree_globs_are_gate_owned() -> None:
    """제품 트리의 **정의역**이 원장 밖에 있음을 못박는다."""
    assert gate.PRODUCT_TREE_GLOBS, "제품 트리 열거가 비었습니다 — 전수 피복이 공허해집니다."
    assert gate.PRODUCT_TREE_GLOBS == ("frontend/**/*",), (
        "제품 트리는 확장자를 열거하지 않고 frontend 전수를 수집해야 합니다 — 새 .ts/.tsx 형식이 "
        "축 밖에서 태어나면 안 됩니다."
    )


def test_product_code_scope_subtracts_the_static_closure_contract() -> None:
    """코드 정의역은 형식 allowlist가 아니라 정적 폐포 계약의 non-code 감산이다."""
    contract = json.loads(
        (REPO_ROOT / "tests" / "static_closure_contract.json").read_text(encoding="utf-8")
    )
    expected = {
        *(f"frontend/**/*{suffix}" for suffix in contract["non_code_suffixes"]),
        "frontend/src/selftest/**",
    }
    assert gate.PRODUCT_CODE_SCOPE == ("frontend/**/*",)
    assert set(gate.PRODUCT_CODE_EXCLUDED) == expected


def test_scope_statement_and_exclusions_are_data_not_prose(document: dict[str, Any]) -> None:
    """「미분류 0」의 범위와 제외 축은 산문 각주가 아니라 머리말 데이터여야 한다."""
    assert document["scope_statement"].strip(), "scope_statement 가 비었습니다."
    assert document.get("repo_wide_metrics") == [], (
        "저장소 전수 scope 계측이 생겼습니다 — 고정 수치가 아니라 base_sha 앵커 + 정당화된 "
        "delta 로 적어야 합니다."
    )
    excluded = {item["axis"]: item for item in document["excluded_axes"]}
    assert "js_planted_data_attrs" not in excluded, (
        "JS/TS 가 심는 data-* 축의 제외가 되살아났습니다 — dom_js_data_attr AST 축이 후계입니다."
    )
    assert "dom_js_data_attr" in document["axes"], "JS/TS data-* 생산자 후계 축이 없습니다."
    assert "selftest_frontend_surface" in excluded, (
        "selftest 트리의 **명시 제외**가 사라졌습니다 — 같은 원장이 alias 에서는 그 트리를 "
        "계상하면서 축에서만 조용히 빼면 「미분류 0」이 거짓말이 됩니다."
    )
    assert excluded["selftest_frontend_surface"]["size"]["current"] > 0, (
        "제외한 표면의 크기가 데이터로 없습니다 — 「안 센다」와 「얼마나 안 세는지 모른다」는 다릅니다."
    )
    assert document.get("unoccupied_classifications") == ["host"], (
        "어휘 5종 중 오늘 점유자가 없는 값의 선언이 사라졌습니다 — 부재도 데이터로 적는다."
    )


#: 복제 트리에서 잴 수 있는 축 — Python 쪽 두 축(`state_snapshot_channel`·`state_ring1`)은
#: 복제가 `src/` 를 담지 않아 **그 트리에서 잴 수 없다**. 없는 파일 때문에 무관한 축이 죽으면
#: 그 음성 대조는 자기가 겨눈 좌표를 증명하지 못한다.
#:
#: 이 이유는 「추출기가 트리를 본다」가 참일 때만 성립한다 — 액션 레지스트리를 import 로 읽던
#: 동안에는 두 축이 복제와 무관하게 **설치본**을 재서 조용히 초록이었다. 그래서 그 추출기를
#: `ast` 로 옮겼고, 이 목록의 사유가 이제 실제와 맞는다.
CLONE_AXES = [
    "dom_static", "dom_data_attr", "dom_js_data_attr", "dom_js_site", "state_js_module",
    "subscription_listener", "subscription_release", "subscription_push",
    "lifecycle_factory", "lifecycle_hook",
]


# ──────────────────────────────────────────────────────────────────────────
# 음성 — 저장소 변이 6 (원장은 한 글자도 안 바꾼다)
# ──────────────────────────────────────────────────────────────────────────


def test_pristine_clone_is_green(document: dict[str, Any], frontend_tree: Path) -> None:
    """아래 여섯 음성 대조의 **양성 대조**.

    복제 자체가 붉으면 N1~N5 는 자기가 만든 변이가 아니라 복제 결함으로 통과할 수 있다.
    변이 없는 트리가 초록임을 먼저 못박아야 그 red 가 변이의 것이라고 말할 수 있다.
    """
    report = gate.check(
        document, frontend_tree, axes=CLONE_AXES, metrics=["innerhtml-assignment"]
    )
    assert report.ok, "변이 없는 복제 트리가 붉습니다 — 음성 대조의 기준면이 깨졌습니다.\n" + _failures(report)


def test_n1_new_root_level_id_is_unclassified(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """N1 — `<body>` 직속에 id 하나를 더하면 `M − C` 가 그것을 좌표로 지목한다."""
    index = clone_source / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "</body>", '<div id="__negctl__"></div>\n</body>', 1
        ),
        encoding="utf-8",
    )
    report = gate.check(document, frontend_tree, axes=["dom_static"], metrics=[])
    assert not report.ok, "루트 직속 새 id 가 미분류로 안 잡혔습니다."
    assert "__negctl__" in _failures(report), _failures(report)


def test_n1b_new_id_inside_a_folded_container_breaks_the_member_count(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """N1b — 접힌 컨테이너 **안쪽** 삽입.

    접기만 있으면 이 삽입은 영영 초록이다(컨테이너 행이 새 자식을 흡수한다).
    `members_expected` 정수 하나가 그 구멍을 닫는다.
    """
    index = clone_source / "index.html"
    text = index.read_text(encoding="utf-8")
    marker = '<div class="status" id="jobStatus"'
    assert marker in text, "N1b 의 삽입 지점이 사라졌습니다 — 음성 대조를 다시 겨눠야 합니다."
    # 같은 줄에 끼운다 — 줄을 늘리면 아래쪽 증거 좌표가 전부 밀려 실패가 22건으로 번지고,
    # 「한 좌표만 바꾼다」가 거짓이 된다. 변이는 최소여야 그 red 가 무엇의 것인지 말할 수 있다.
    index.write_text(
        text.replace(marker, '<div id="__negctl_job__"></div>' + marker, 1), encoding="utf-8"
    )
    report = gate.check(document, frontend_tree, axes=["dom_static"], metrics=[])
    assert not report.ok, "접힌 컨테이너 안쪽 성장이 안 잡혔습니다."
    assert len(report.failures) == 1, "변이 하나가 실패 하나여야 합니다.\n" + _failures(report)
    assert "scr-job" in _failures(report), _failures(report)
    assert "members_expected" in _failures(report), _failures(report)


def test_n2_new_listener_site_is_unclassified(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """N2 — 구독 사이트가 하나 늘면 그 파일:줄 이 미분류로 나온다."""
    target = clone_source / "js" / "theme.js"
    target.write_text(
        target.read_text(encoding="utf-8") + '\ndocument.addEventListener("click", () => {});\n',
        encoding="utf-8",
    )
    report = gate.check(document, frontend_tree, axes=["subscription_listener"], metrics=[])
    assert not report.ok, "새 구독 사이트가 미분류로 안 잡혔습니다."
    assert "frontend/js/theme.js:" in _failures(report), _failures(report)


def test_n3_deleted_assignment_moves_the_metric_only(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """N3 — `innerHTML =` 대입을 하나 지우면 **계측 불일치만** 난다.

    유령 행은 나지 않는다. `innerHTML` 은 `[[metric]]` 이고 노드 축이 아니기 때문이다 —
    두 종류를 섞어 기대하면 음성 대조가 자기 스키마를 잘못 안다는 뜻이 된다.
    """
    # R4-02 가 `sheet_picker.js` 를 지우면서 겨눔을 옮겼다. 변이는 **하나**로 유지한다 —
    # 파일 안 대입 수를 먼저 못박고 그중 하나만 지운다(전역 술어 치환은 자기가 겨눈 것과
    # 다른 구멍까지 함께 감춘다).
    target = clone_source / "js" / "grouplist.js"
    lines = target.read_text(encoding="utf-8").splitlines()
    hits = [index for index, line in enumerate(lines) if re.search(r"innerHTML\s*=[^=]", line)]
    assert len(hits) == 2, "grouplist.js 의 대입 수가 바뀌었습니다 — 변이를 다시 겨눠야 합니다."
    kept = [line for index, line in enumerate(lines) if index != hits[0]]
    target.write_text("\n".join(kept) + "\n", encoding="utf-8")

    report = gate.check(document, frontend_tree, axes=[], metrics=["innerhtml-assignment"])
    assert not report.ok, "계측 재실측이 안 붉었습니다."
    assert report.metric_mismatch, "계측이 아닌 다른 축에서 붉었습니다."
    assert "innerhtml-assignment" in _failures(report), _failures(report)
    assert not any(axis.ghost for axis in report.axes.values()), "유령 행은 나면 안 됩니다."


def test_n4_removed_state_declaration_becomes_a_ghost_row(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """N4 — 코드가 사라지고 원장이 남으면 `C − M` 이 그 좌표를 든다."""
    # R4-02 가 `screens/workbench.js` 를 지우면서 남은 legacy 화면으로 겨눔을 옮겼다.
    target = clone_source / "js" / "screens" / "job.js"
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() != "let wired = false;"]
    assert len(kept) == len(lines) - 1, "job.js 의 `let wired` 좌표가 바뀌었습니다."
    target.write_text("\n".join(kept) + "\n", encoding="utf-8")

    report = gate.check(document, frontend_tree, axes=["state_js_module"], metrics=[])
    assert not report.ok, "사라진 상태 선언이 유령 행으로 안 잡혔습니다."
    assert "유령" in _failures(report), _failures(report)
    assert "wired" in _failures(report), _failures(report)


def test_n5_zero_indent_module_state_is_seen(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """N5 — **0칸 최상위** 상태 선언.

    옛 2칸 들여쓰기 관례 술어였다면 이 변이는 영영 초록이다. AST 인구조사로 옮긴 이유가
    이것이고, 그 회귀를 여기서 막는다.
    """
    target = clone_source / "js" / "modal.js"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nlet __neg = null;\n", encoding="utf-8"
    )
    report = gate.check(document, frontend_tree, axes=["state_js_module"], metrics=[])
    assert not report.ok, "0칸 최상위 상태가 미분류로 안 잡혔습니다."
    assert "__neg" in _failures(report), _failures(report)


@pytest.mark.parametrize(
    ("relative", "source", "expected"),
    [
        ("js/theme.js", '\nconst __r3Markup = `<i data-r3-markup="1"></i>`;\n', "data-r3-markup"),
        (
            "src/react/root.ts",
            '\nconst __R3_SET = "data-r3-set"; document.body.setAttribute(__R3_SET, "1");\n',
            "data-r3-set",
        ),
        ("js/theme.js", "\ndocument.body.dataset.r3Dataset = \"1\";\n", "data-r3-dataset"),
        (
            "src/react/root.ts",
            '\nel("div", { "data-r3-prop": "1" });\n',
            "data-r3-prop",
        ),
    ],
)
def test_js_data_attribute_producer_forms_are_seen(
    document: dict[str, Any], clone_source: Path, relative: str, source: str, expected: str,
) -> None:
    """마크업·setAttribute(+모듈 const)·dataset·React 객체 속성 네 생산형을 AST가 본다."""
    target = clone_source / relative
    target.write_text(target.read_text(encoding="utf-8") + source, encoding="utf-8")
    report = gate.check(document, clone_source.parent, axes=["dom_js_data_attr"], metrics=[])
    assert not report.ok, f"{expected} 생산자가 미분류로 안 잡혔습니다."
    assert expected in _failures(report), _failures(report)


@pytest.mark.parametrize(
    ("relative", "source", "form"),
    [
        (
            "js/theme.js",
            '\nconst __r3Name = window.name; document.body.setAttribute(__r3Name, "1");\n',
            "dynamic-set-attribute",
        ),
        (
            "js/theme.js",
            '\ndocument.body.dataset[window.name] = "1";\n',
            "computed-dataset",
        ),
        (
            "js/theme.js",
            '\nconst __r3DynamicMarkup = `<i data-${window.name}="1"></i>`;\n',
            "dynamic-markup-name",
        ),
        (
            "src/react/root.ts",
            '\nel("div", { ...window.__r3Props });\n',
            "jsx-spread",
        ),
    ],
)
def test_dynamic_js_data_attribute_name_moves_the_blind_spot(
    document: dict[str, Any], clone_source: Path, relative: str, source: str, form: str,
) -> None:
    """네 동적 생산형은 조용히 빠지지 않고 이름 있는 사각 크기를 움직인다."""
    target = clone_source / relative
    target.write_text(
        target.read_text(encoding="utf-8") + source,
        encoding="utf-8",
    )
    report = gate.check(document, clone_source.parent, axes=["dom_js_data_attr"], metrics=[])
    assert not report.ok, "동적 data-* 이름이 사각 크기를 움직이지 않았습니다."
    assert "사각이 움직였습니다" in _failures(report), _failures(report)
    assert form in _failures(report), _failures(report)


def test_js_data_attribute_axis_excludes_selftest(
    document: dict[str, Any], clone_source: Path,
) -> None:
    target = clone_source / "src" / "selftest" / "api.js"
    target.write_text(
        target.read_text(encoding="utf-8") + '\nconst __r3 = `<i data-r3-selftest></i>`;\n',
        encoding="utf-8",
    )
    report = gate.check(document, clone_source.parent, axes=["dom_js_data_attr"], metrics=[])
    assert report.ok, "selftest 생산자가 제품 data-* 축으로 샜습니다.\n" + _failures(report)


def test_js_data_attribute_selectors_and_reads_are_not_producers(
    document: dict[str, Any], clone_source: Path,
) -> None:
    target = clone_source / "js" / "theme.js"
    target.write_text(
        target.read_text(encoding="utf-8")
        + '\ndocument.querySelector("[data-r3-read]");\n'
        + 'document.body.getAttribute("data-r3-read");\n'
        + 'const __r3Read = document.body.dataset.r3Read;\n',
        encoding="utf-8",
    )
    report = gate.check(document, clone_source.parent, axes=["dom_js_data_attr"], metrics=[])
    assert report.ok, "selector/getAttribute/dataset read가 생산자로 오검됐습니다.\n" + _failures(report)


# ──────────────────────────────────────────────────────────────────────────
# 음성 — 원장 변이 9 (저장소는 한 글자도 안 바꾼다)
# ──────────────────────────────────────────────────────────────────────────


def test_n6_wrong_metric_value_is_remeasured(mutable_document: dict[str, Any]) -> None:
    """N6 — 계측값 ±1."""
    metric = next(m for m in mutable_document["metric"] if m["id"] == "innerhtml-assignment")
    metric["value"] = metric["value"] + 1
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=["innerhtml-assignment"])
    assert not report.ok, "기록값과 재실측의 차이가 안 잡혔습니다."
    assert "innerhtml-assignment" in _failures(report), _failures(report)


@pytest.mark.parametrize("dropped", ["predicate", "scope", "unit"])
def test_n7_metric_without_the_predicate_triple_is_a_structural_error(
    mutable_document: dict[str, Any], dropped: str
) -> None:
    """N7 — 술어 3종 중 **하나만** 빼도 항목이 성립하지 않는다."""
    metric = next(m for m in mutable_document["metric"] if m["id"] == "push-subscription-sites")
    metric.pop(dropped)
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=["push-subscription-sites"])
    assert not report.ok, f"`{dropped}` 없는 계측 항목이 통과했습니다."
    assert dropped in _failures(report), _failures(report)
    assert "push-subscription-sites" in _failures(report), _failures(report)


def test_n8_uppercase_classification_is_rejected(mutable_document: dict[str, Any]) -> None:
    """N8 — 분류 어휘는 **소문자 5종**이다. 한 글자 변형이 enum 을 깨야 한다."""
    mutable_document["node"][0]["classification"] = "React"
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "대문자 분류값이 통과했습니다."
    assert "React" in _failures(report), _failures(report)
    assert mutable_document["node"][0]["id"] in _failures(report), _failures(report)


def test_n9_deleted_node_row_leaves_members_unclassified(
    mutable_document: dict[str, Any]
) -> None:
    """N9 — 노드 행 하나를 지우면 그 멤버가 미분류로 나온다.

    (표본은 R3-02 재고정으로 state/app-shell 이 행째 소멸해 state/data-picker 로 옮겼다 —
    변이의 요지는 「측정되는 멤버를 가진 행」이면 어느 행이든 같다.)
    """
    victim = next(
        node for node in mutable_document["node"] if node["id"] == "state/data-picker"
    )
    members = victim["selector"]["members"]
    mutable_document["node"].remove(victim)
    report = gate.check(mutable_document, REPO_ROOT, axes=["state_js_module"], metrics=[])
    assert not report.ok, "지운 행의 멤버가 미분류로 안 잡혔습니다."
    for member in members:
        assert member in _failures(report), _failures(report)


def test_n10_row_for_a_nonexistent_node_is_a_ghost(mutable_document: dict[str, Any]) -> None:
    """N10 — 저장소에 없는 좌표를 든 행은 유령이다."""
    victim = next(
        node for node in mutable_document["node"] if node["id"] == "state/data-picker"
    )
    victim["selector"]["members"] = [*victim["selector"]["members"], "frontend/js/ghost.js:1 X"]
    report = gate.check(mutable_document, REPO_ROOT, axes=["state_js_module"], metrics=[])
    assert not report.ok, "실재하지 않는 멤버가 유령으로 안 잡혔습니다."
    assert "frontend/js/ghost.js:1 X" in _failures(report), _failures(report)


def test_n11_evidence_anchor_must_be_on_that_line(mutable_document: dict[str, Any]) -> None:
    """N11 — `line` 은 그대로 두고 `anchor` 만 바꾼다.

    「파일 존재 + 행수 ≥ line」만 보는 증거 해석이었다면 824행 문서의 아무 줄이나 초록이다.
    집필 중 남의 커밋이 상수를 15줄 민 사건이 이 필드의 실물 확증이다.
    """
    victim = mutable_document["node"][0]
    victim["evidence"][0]["anchor"] = "__anchor_that_is_not_there__"
    report = gate.check(mutable_document, REPO_ROOT, axes=["dom_static"], metrics=[])
    assert not report.ok, "틀린 앵커가 통과했습니다."
    assert "__anchor_that_is_not_there__" in _failures(report), _failures(report)
    assert victim["id"] in _failures(report), _failures(report)


def test_n12_react_row_without_a_handoff_slice_is_rejected(
    mutable_document: dict[str, Any]
) -> None:
    """N12 — `react` 행은 이관 슬라이스를 든다. 배정 없는 이관은 무주공산이다."""
    victim = next(
        node for node in mutable_document["node"] if node.get("classification") == "react"
    )
    victim.pop("handoff_slice")
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "슬라이스 없는 react 행이 통과했습니다."
    assert "handoff_slice" in _failures(report), _failures(report)
    assert victim["id"] in _failures(report), _failures(report)


def test_n13_p_review_row_with_a_blank_evidence_field_is_rejected(
    mutable_document: dict[str, Any]
) -> None:
    """N13 — G15 의 기계 판독 형태. 5증거 중 **하나만** 공란이어도 붉는다."""
    victim = next(
        node
        for node in mutable_document["node"]
        if node.get("classification") == "p_review_required"
    )
    victim["p_review"]["call_path"] = ""
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "공란 증거가 통과했습니다."
    assert "call_path" in _failures(report), _failures(report)
    assert victim["id"] in _failures(report), _failures(report)


def test_n14_blind_spot_size_is_remeasured(mutable_document: dict[str, Any]) -> None:
    """N14 — 사각이 데이터임을 증명하는 유일한 케이스.

    `current` 를 하나 줄이면 프로브 재실행이 그 차이를 낸다. 사각을 없애지는 못해도
    **조용히 자라지는 못한다**.
    """
    blind = mutable_document["axes"]["state_js_module"]["blind_spot"]
    blind["current"] = blind["current"] - 1
    report = gate.check(mutable_document, REPO_ROOT, axes=["state_js_module"], metrics=[])
    assert not report.ok, "사각 크기 불일치가 안 잡혔습니다."
    assert "사각이 움직였습니다" in _failures(report), _failures(report)
    assert "state_js_module" in _failures(report), _failures(report)


# ──────────────────────────────────────────────────────────────────────────
# 음성 — 반증 라운드가 뚫은 자리 (분모 · 제외 · 전수 선언 · 미겨눔 분기)
# ──────────────────────────────────────────────────────────────────────────


def test_m15_empty_ledger_is_refused(document: dict[str, Any]) -> None:
    """M15 — **빈 원장**. 축 0·노드 0·계측 0 이 통과하면 「미분류 0」은 명제가 아니다."""
    empty = {
        "schema": 1,
        "baseline_sha": document["baseline_sha"],
        "scope_statement": document["scope_statement"],
        "repo_wide_metrics": [],
        "extractors": {},
        "axes": {},
        "node": [],
        "metric": [],
        "review_item": [],
        "excluded_axes": [],
    }
    report = gate.check(empty, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "빈 원장이 통과했습니다 — 분모가 원장의 자유 변수입니다."
    text = _failures(report)
    assert "원장에서 축이 사라졌습니다" in text, text
    assert "계측 항목 목록" in text, text
    assert "판정 요구 항목 목록" in text, text
    assert "명시 제외 축 목록" in text, text
    assert "노드 행" in text, text


def test_m8_deleting_an_axis_is_refused(mutable_document: dict[str, Any]) -> None:
    """M8 — 축 선언 + 그 행 + 계측을 함께 지워도 붉어야 한다."""
    mutable_document["axes"].pop("subscription_release")
    mutable_document["node"] = [
        node for node in mutable_document["node"] if node["axis"] != "subscription_release"
    ]
    mutable_document["metric"] = [
        metric for metric in mutable_document["metric"]
        if metric["id"] != "listener-release-sites"
    ]
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "축을 통째로 지운 원장이 통과했습니다."
    assert "subscription_release" in _failures(report), _failures(report)


def test_m12_narrowing_a_regex_axis_scope_trips_the_floor(
    mutable_document: dict[str, Any]
) -> None:
    """M12 — regex 축의 scope 를 좁히고 밖의 행을 정리하면 계수만으로는 안 붉는다.

    저장소에 앵커된 **측정 하한**이 그 축소를 잡는다.
    """
    axis = mutable_document["axes"]["subscription_listener"]
    axis["scope"] = ["frontend/js/screens/*.js"]
    axis["scope_excluded"] = []
    report = gate.check(mutable_document, REPO_ROOT, axes=["subscription_listener"], metrics=[])
    assert not report.ok, "scope 축소가 통과했습니다."
    text = _failures(report)
    assert "게이트 하한" in text, text
    assert "subscription_listener" in text, text


def test_m7b_dom_api_id_planting_grows_the_blind_spot(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """M7b′ — 마크업 문자열이 아니라 **DOM API** 로 id 를 심는 길.

    「못 보는 네 형태」를 전수라고 선언했던 자리다. 다섯째·여섯째를 프로브에 편입했으므로
    이제 사각이 자라고 붉는다.
    """
    target = clone_source / "js" / "theme.js"
    target.write_text(
        target.read_text(encoding="utf-8")
        + '\nfunction __negHelper(el) { el.setAttribute("id", "sneakyB"); el.id = "sneakyC"; }\n',
        encoding="utf-8",
    )
    report = gate.check(document, frontend_tree, axes=["dom_js_site"], metrics=[])
    assert not report.ok, "DOM API 로 심는 id 가 사각에서 안 잡혔습니다."
    text = _failures(report)
    assert "사각이 움직였습니다" in text, text
    assert "set-attribute" in text and "id-property-assignment" in text, text


def test_m7c_new_module_under_src_subdirectory_is_seen(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """M7c″ — `frontend/src/<하위>/store.js` 신설.

    scope 가 `frontend/src/*.js` **비재귀**였을 때 이 파일은 상태와 팩토리를 들고 와도
    전 축 밖이었다. 재귀로 넓히고 selftest 만 명시 제외한 것이 이 대조의 값이다.
    """
    module = clone_source / "src" / "newfeature" / "store.js"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("let __srcState = 1;\nexport function bump() { __srcState += 1; }\n",
                      encoding="utf-8")
    report = gate.check(
        document, frontend_tree, axes=["state_js_module", "lifecycle_factory"], metrics=[]
    )
    assert not report.ok, "src 하위 신설 모듈이 축 밖이었습니다."
    text = _failures(report)
    assert "frontend/src/newfeature/store.js:1 __srcState" in text, text
    assert "frontend/src/newfeature/store.js:2" in text, text


def test_s4_new_mjs_module_is_seen(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """S4 — `.mjs` 확장자. 저장소는 이미 `.mjs` 를 쓰는데 전 축의 글롭이 `.js` 뿐이었다."""
    module = clone_source / "js" / "sneaky.mjs"
    module.write_text("let __mjsState = 1;\n", encoding="utf-8")
    report = gate.check(document, frontend_tree, axes=["state_js_module"], metrics=[])
    assert not report.ok, "`.mjs` 신설 모듈이 축 밖이었습니다."
    assert "frontend/js/sneaky.mjs:1 __mjsState" in _failures(report), _failures(report)


def test_s3_non_utf8_source_is_a_structural_error(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """S3 — UTF-8 로 못 읽는 `.js`.

    조용히 `continue` 하면 정규식 축은 그 파일을 못 보고 AST 축은 본다. 「런타임 부재를 자동
    감지해 조용히 스킵하지 않는다」와 같은 축이라 구조 오류로 든다.
    """
    target = clone_source / "js" / "badenc.js"
    target.write_bytes("// 한글 주석\nwindow.addEventListener(\"click\", () => {});\n".encode("cp949"))
    report = gate.check(document, frontend_tree, axes=["subscription_listener"], metrics=[])
    assert not report.ok, "비-UTF8 소스가 조용히 스킵됐습니다."
    text = _failures(report)
    assert "frontend/js/badenc.js" in text, text
    assert "UTF-8" in text, text


def test_s2_anchor_occurrence_catches_a_shifted_line(mutable_document: dict[str, Any]) -> None:
    """S2 — 앵커가 「그 줄의 부분열」이면 반복 토큰 구간에서 줄이 밀려도 초록이었다."""
    victim = next(
        node for node in mutable_document["node"] if node["id"] == "subscription/listener/app-shell"
    )
    evidence = victim["evidence"][0]
    assert evidence.get("occurrence"), "이 행은 유일하지 않은 앵커를 들고 있어야 대조가 성립한다."
    source = (REPO_ROOT / evidence["file"]).read_text(encoding="utf-8").splitlines()
    hits = [n for n, line in enumerate(source, 1) if evidence["anchor"] in line]
    moved = next(n for n in hits if n != evidence["line"])
    evidence["line"] = moved
    report = gate.check(mutable_document, REPO_ROOT, axes=["subscription_listener"], metrics=[])
    assert not report.ok, "같은 앵커를 가진 다른 줄로 밀렸는데 통과했습니다."
    text = _failures(report)
    assert "occurrence" in text, text
    assert victim["id"] in text, text


def test_s5_derived_metric_scope_must_match_a_pathless_axis(
    mutable_document: dict[str, Any]
) -> None:
    """M9′/S5 — 멤버 키에 경로가 없는 축에서는 scope 필터가 아무것도 안 거른다.

    그러면 v2 §2 의 세 필드 중 하나가 장식이 된다. 파생 계측은 축 scope 를 그대로 상속한다.
    """
    metric = next(m for m in mutable_document["metric"] if m["id"] == "dom-stable-ids")
    metric["scope"] = ["nonexistent/never.html"]
    report = gate.check(
        mutable_document, REPO_ROOT, axes=["dom_static"], metrics=["dom-stable-ids"]
    )
    assert not report.ok, "경로 없는 축의 파생 scope 위조가 통과했습니다."
    text = _failures(report)
    assert "scope 필터가 아무것도" in text, text
    assert "dom-stable-ids" in text, text


def test_m13_verification_pointing_at_a_missing_test_is_refused(
    mutable_document: dict[str, Any]
) -> None:
    """M13 — `verification` 이 없는 테스트 함수를 가리키면 붉는다(**전체 실행 전용 분기**)."""
    victim = next(
        node for node in mutable_document["node"]
        if node["verification"] != ["none"]
    )
    victim["verification"] = ["tests/test_web_dom_contract.py::test_this_function_does_not_exist"]
    report = gate.check(mutable_document, REPO_ROOT, metrics=[])
    assert not report.ok, "없는 테스트를 가리키는 verification 이 통과했습니다."
    text = _failures(report)
    assert "test_this_function_does_not_exist" in text, text
    assert victim["id"] in text, text


@pytest.mark.parametrize("dropped", ["predicate", "scope", "unit"])
def test_m21_axis_level_predicate_triple_is_required(
    mutable_document: dict[str, Any], dropped: str
) -> None:
    """M21 — 술어 3종은 계측만이 아니라 **축 선언에도** 예외 없이 걸린다."""
    mutable_document["axes"]["subscription_release"].pop(dropped)
    report = gate.check(mutable_document, REPO_ROOT, axes=["subscription_release"], metrics=[])
    assert not report.ok, f"축 수준 `{dropped}` 누락이 통과했습니다."
    text = _failures(report)
    assert dropped in text, text
    assert "subscription_release" in text, text


@pytest.mark.parametrize("dropped", ["__all__", "description", "probe", "scope", "current"])
def test_m22_blind_spot_fields_are_required(
    mutable_document: dict[str, Any], dropped: str
) -> None:
    """M22·M23 — `blind_spot` 통째 삭제와 다섯 필드 각각. 사각 진술은 선택이 아니다."""
    axis = mutable_document["axes"]["subscription_push"]
    if dropped == "__all__":
        axis.pop("blind_spot")
    else:
        axis["blind_spot"].pop(dropped)
    report = gate.check(mutable_document, REPO_ROOT, axes=["subscription_push"], metrics=[])
    assert not report.ok, f"`blind_spot` 의 `{dropped}` 누락이 통과했습니다."
    text = _failures(report)
    assert "blind_spot" in text, text
    assert "subscription_push" in text, text


def test_false_positive_direction_is_remeasured(mutable_document: dict[str, Any]) -> None:
    """오검 방향도 사각과 같은 규칙으로 재실측된다 — 「18개 팩토리」가 붉은 자리."""
    claim = mutable_document["axes"]["lifecycle_factory"]["false_positive"]
    claim["current"] = claim["current"] + 1
    report = gate.check(mutable_document, REPO_ROOT, axes=["lifecycle_factory"], metrics=[])
    assert not report.ok, "오검 크기 불일치가 안 잡혔습니다."
    text = _failures(report)
    assert "false_positive" in text, text
    assert "lifecycle_factory" in text, text


def test_excluded_axis_size_is_remeasured(mutable_document: dict[str, Any]) -> None:
    """명시 제외 축의 **크기**도 데이터다 — 「소리 나는 제외」의 기계 형태."""
    excluded = next(
        item for item in mutable_document["excluded_axes"]
        if item["axis"] == "selftest_frontend_surface"
    )
    excluded["size"]["current"] = excluded["size"]["current"] - 1
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "제외한 표면의 크기 불일치가 안 잡혔습니다."
    assert "selftest_frontend_surface" in _failures(report), _failures(report)


def test_excluded_surface_growth_is_loud(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """제외한 트리가 **자라면** 붉는다 — 조용한 유예와 소리 나는 제외를 가르는 자리."""
    module = clone_source / "src" / "selftest" / "__neg_probe.js"
    module.write_text("export function __negProbe() { return 1; }\n", encoding="utf-8")
    report = gate.check(document, frontend_tree, axes=[], metrics=[])
    assert not report.ok, "제외한 표면이 자랐는데 조용했습니다."
    text = _failures(report)
    assert "selftest_frontend_surface" in text, text
    assert "제외는 소리 나야 합니다" in text, text


def test_repo_wide_scope_must_be_declared(mutable_document: dict[str, Any]) -> None:
    """저장소 전수 scope 는 관측자 오염에 노출된다 — 선언 없이 생기면 붉는다."""
    metric = next(
        m for m in mutable_document["metric"] if m["id"] == "push-subscription-sites"
    )
    metric["aliases"][0]["scope"] = ["**/*.js"]
    report = gate.check(
        mutable_document, REPO_ROOT, axes=[], metrics=["push-subscription-sites"]
    )
    assert not report.ok, "저장소 전수 scope 가 선언 없이 통과했습니다."
    assert "repo_wide_metrics" in _failures(report), _failures(report)


def test_baseline_sha_must_be_a_commit_hash(mutable_document: dict[str, Any]) -> None:
    """재고정이 계약인 원장에서 `baseline_sha` 가 산문이면 안 된다."""
    mutable_document["baseline_sha"] = "8fcc30e"
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "짧은 해시가 통과했습니다."
    assert "baseline_sha" in _failures(report), _failures(report)


def test_review_item_five_evidence_is_required(mutable_document: dict[str, Any]) -> None:
    """G15 는 노드 표와 **판정 요구 표 양쪽**에 걸린다 — 음성 대조가 한쪽만 겨눴던 자리."""
    victim = next(
        item for item in mutable_document["review_item"] if item.get("requires_p_review")
    )
    victim["p_review"]["call_path"] = ""
    report = gate.check(mutable_document, REPO_ROOT, metrics=[])
    assert not report.ok, "판정 요구 항목의 공란 증거가 통과했습니다."
    text = _failures(report)
    assert "call_path" in text, text
    assert victim["id"] in text, text


def test_review_item_resolution_is_machine_readable(
    mutable_document: dict[str, Any],
) -> None:
    victim = next(item for item in mutable_document["review_item"] if item["resolved"])
    victim["resolved"] = "done"
    report = gate.check(mutable_document, REPO_ROOT, metrics=[])
    assert not report.ok, "문자열 resolved가 통과했습니다."
    assert "resolved" in _failures(report) and victim["id"] in _failures(report)


def test_resolved_review_item_requires_a_disposition(
    mutable_document: dict[str, Any],
) -> None:
    victim = next(item for item in mutable_document["review_item"] if item["resolved"])
    victim.pop("disposition")
    report = gate.check(mutable_document, REPO_ROOT, metrics=[])
    assert not report.ok, "처분 없는 resolved=true가 통과했습니다."
    assert "disposition" in _failures(report) and victim["id"] in _failures(report)


def test_extractor_table_backing_must_match_the_implementation(
    mutable_document: dict[str, Any]
) -> None:
    """`[extractors.*]` 의 `backing` 은 산문이 아니라 구현과의 대조 대상이다."""
    mutable_document["extractors"]["html_ids"]["backing"] = "regex-convention"
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "추출기 표의 거짓 backing 이 통과했습니다."
    assert "html_ids" in _failures(report), _failures(report)


def test_named_extractor_scope_cannot_be_rewritten_by_the_ledger(
    mutable_document: dict[str, Any]
) -> None:
    """이름 붙은 추출기의 scope·scope_excluded 는 코드가 든다 — 원장이 혼자 다시 못 쓴다."""
    mutable_document["axes"]["state_js_module"]["scope_excluded"] = []
    report = gate.check(mutable_document, REPO_ROOT, axes=["state_js_module"], metrics=[])
    assert not report.ok, "추출기 scope_excluded 위조가 통과했습니다."
    assert "scope_excluded" in _failures(report), _failures(report)


# ──────────────────────────────────────────────────────────────────────────
# 음성 — 재검증 라운드가 뚫은 자리 (분모의 **정의역**)
# ──────────────────────────────────────────────────────────────────────────


def test_m26_silent_shrink_inside_the_floor_slack_is_refused(
    mutable_document: dict[str, Any]
) -> None:
    """M26 — 축 `scope_excluded` 로 한 파일의 리스너 표면 13건을 통째로 지운다.

    하한은 **구간**이라 「측정 − 하한」만큼 무음 삭감 예산이 남는다. 축의 측정 계약을 게이트가
    지문으로 들면 그 예산 안에서도 붉는다 — 분모를 밖에 뒀어도 **정의역**이 안에 있으면
    같은 자리로 돌아온다.
    """
    axis = mutable_document["axes"]["subscription_listener"]
    axis["scope_excluded"] = [*axis["scope_excluded"], "frontend/js/screens/workbench.js"]
    mutable_document["node"] = [
        node for node in mutable_document["node"]
        if node["id"] != "subscription/listener/workbench"
    ]
    metric = next(
        m for m in mutable_document["metric"] if m["id"] == "listener-attach-sites"
    )
    metric["value"] = 106
    metric["scope_excluded"] = axis["scope_excluded"]
    report = gate.check(mutable_document, REPO_ROOT)
    assert not report.ok, "하한 여유분 안의 무음 삭감이 통과했습니다."
    text = _failures(report)
    assert "측정 계약이 게이트가 든 지문과 다릅니다" in text, text
    assert "subscription_listener" in text, text


def test_m24_narrowing_a_predicate_is_refused(
    mutable_document: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """M24 — 술어를 좁히고 행을 지우고 **하한까지 함께 낮춘** 경우.

    하한만이 앵커였을 때는 파일 둘만 고치면 축의 절반이 조용히 사라졌다.
    """
    hook = mutable_document["axes"]["lifecycle_hook"]
    hook["predicate"]["pattern"] = hook["predicate"]["pattern"].replace(
        "Preserve\\.around\\s*\\(|", ""
    )
    mutable_document["node"] = [
        node for node in mutable_document["node"] if node["id"] != "lifecycle/preserve-around"
    ]
    monkeypatch.setitem(gate.AXIS_FLOORS, "lifecycle_hook", 4)
    report = gate.check(mutable_document, REPO_ROOT, axes=["lifecycle_hook"], metrics=[])
    assert not report.ok, "술어 축소가 하한 인하와 함께 통과했습니다."
    assert "측정 계약이 게이트가 든 지문과 다릅니다" in _failures(report), _failures(report)


def test_m24b_lowering_every_floor_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """M24b — 게이트의 하한을 전부 1로 낮추는 극단. 값 앵커가 이 파일에도 있어야 한다."""
    for name in gate.AXIS_FLOORS:
        monkeypatch.setitem(gate.AXIS_FLOORS, name, 1)
    with pytest.raises(AssertionError):
        test_axis_contract_is_anchored_outside_the_gate()


def test_new_product_code_file_is_collected_by_the_subtraction_scope(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """감산형 전수 — 새 제품 코드 파일은 확장자 allowlist 없이 기존 축의 실측에 든다."""
    module = clone_source / "widgets" / "card.js"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("export const Card = {};\n", encoding="utf-8")
    report = gate.check(document, frontend_tree, axes=["lifecycle_factory"], metrics=[])
    assert not report.ok, "신설 제품 코드 파일이 감산형 축 밖에서 조용히 통과했습니다."
    text = _failures(report)
    assert "frontend/widgets/card.js:1" in text and "사각이 움직였습니다" in text, text


def test_ts_state_is_inside_the_inventory_definition(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
) -> None:
    """R3-99 F1 — 완료 표면의 TypeScript 상태가 JS 전용 scope 밖으로 빠지지 않는다."""
    target = clone_source / "src" / "shell" / "host.ts"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nlet __r3AuditState = 0;\n",
        encoding="utf-8",
    )
    report = gate.check(document, frontend_tree, axes=["state_js_module"], metrics=[])
    assert not report.ok, "ShellHost의 새 TypeScript 모듈 상태가 조용히 통과했습니다."
    text = _failures(report)
    assert "frontend/src/shell/host.ts" in text and "__r3AuditState" in text, text


def test_tsx_generated_id_is_inside_the_dom_inventory(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
) -> None:
    """R3-99 F2 — TSX가 생산하는 id도 dom_js_site의 측정 집합에 든다."""
    target = clone_source / "src" / "shell" / "__r3_audit.tsx"
    target.write_text(
        "export function Audit(){ return <div id=\"r3AuditTsx\" />; }\n",
        encoding="utf-8",
    )
    report = gate.check(document, frontend_tree, axes=["dom_js_site"], metrics=[])
    assert not report.ok, "TSX가 생산한 id가 dom_js_site 밖에서 조용히 통과했습니다."
    text = _failures(report)
    assert "frontend/src/shell/__r3_audit.tsx" in text and "r3AuditTsx" in text, text


@pytest.mark.parametrize(
    ("suffix", "body", "state_name", "dom_id"),
    [
        (
            ".jsx",
            'let __r3JsxState = 0;\nexport default () => <div id="r3AuditJsx" />;\n',
            "__r3JsxState",
            "r3AuditJsx",
        ),
        (
            ".mts",
            'let __r3MtsState = 0;\nexport const markup = \'<div id="r3AuditMts"></div>\';\n',
            "__r3MtsState",
            "r3AuditMts",
        ),
    ],
)
def test_new_code_suffixes_enter_state_and_dom_axes(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
    suffix: str, body: str, state_name: str, dom_id: str,
) -> None:
    """감산 결과의 새 코드 접미사는 AST 축에 들어오거나 parser가 시끄럽게 실패해야 한다."""
    target = clone_source / "src" / "shell" / f"__r3_suffix_audit{suffix}"
    target.write_text(body, encoding="utf-8")

    report = gate.check(
        document,
        frontend_tree,
        axes=["state_js_module", "dom_js_site"],
        metrics=[],
    )

    assert not report.ok, f"{suffix} 제품 코드가 state/dom 축 밖에서 조용히 통과했습니다."
    text = _failures(report)
    assert state_name in text and dom_id in text, text


@pytest.mark.parametrize(
    ("metric_id", "snippet", "needle"),
    [
        (
            "react-direct-dom-mutations",
            'document.createElement("div");',
            "document.createElement",
        ),
        (
            "react-direct-dom-mutations",
            'document.body.innerHTML = "<div></div>";',
            "innerHTML",
        ),
        (
            "react-listener-cleanup-gaps",
            'window.addEventListener("r3-audit-zombie", () => undefined);',
            "r3-audit-zombie",
        ),
        (
            "react-listener-cleanup-gaps",
            'window.addEventListener("r3-audit-identity", () => undefined);\n'
            'window.removeEventListener("r3-audit-identity", () => undefined);',
            "r3-audit-identity",
        ),
        (
            "react-listener-cleanup-gaps",
            '{ const __r3Target = window; const __r3Handler = () => undefined; '
            '__r3Target.addEventListener("r3-audit-shadow", __r3Handler); }\n'
            '{ const __r3Target = window; const __r3Handler = () => undefined; '
            '__r3Target.removeEventListener("r3-audit-shadow", __r3Handler); }',
            "r3-audit-shadow",
        ),
        (
            "react-listener-cleanup-gaps",
            'const __r3SignalHandler = () => undefined;\n'
            'window.addEventListener("r3-audit-signal", __r3SignalHandler, '
            '{ signal: undefined });',
            "r3-audit-signal",
        ),
        (
            "react-listener-cleanup-gaps",
            'const __r3OnceHandler = () => undefined;\n'
            'window.addEventListener("r3-audit-once", __r3OnceHandler, { once: true });',
            "r3-audit-once",
        ),
        (
            "react-listener-cleanup-gaps",
            'const __r3Controller = new AbortController();\n'
            'const __r3AbortHandler = () => undefined;\n'
            'window.addEventListener("r3-audit-abort", __r3AbortHandler, '
            '{ signal: __r3Controller.signal });',
            "r3-audit-abort",
        ),
        (
            "react-direct-dom-mutations",
            'const __r3BoundCreate = document.createElement.bind(document);\n'
            '__r3BoundCreate("div");',
            "document.createElement",
        ),
        (
            "react-direct-dom-mutations",
            'const { createElement: __r3DestructuredCreate } = document;\n'
            '__r3DestructuredCreate("div");',
            "document.createElement",
        ),
        (
            "react-direct-dom-mutations",
            'document.createElement.call(document, "div");',
            "document.createElement",
        ),
    ],
)
def test_completed_react_host_negative_gates_reject_audit_mutants(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
    metric_id: str, snippet: str, needle: str,
) -> None:
    """R3-99 통제 변이 — React host의 직접 DOM과 미해제 리스너는 반드시 red다."""
    target = clone_source / "src" / "shell" / "host.ts"
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n{snippet}\n",
        encoding="utf-8",
    )
    report = gate.check(document, frontend_tree, axes=[], metrics=[metric_id])
    assert not report.ok, f"{metric_id} 통제 변이가 조용히 통과했습니다."
    text = _failures(report)
    assert metric_id in text and needle in text, text


@pytest.mark.parametrize("mutation", ["ghost-member", "wrong-axes", "fabricated"])
def test_cross_axis_overlap_is_derived_not_declared(
    mutable_document: dict[str, Any], mutation: str
) -> None:
    """교차 겹침은 **측정에서 유도**된다 — 신설 필드가 거짓을 적기 쉬운 자리였다.

    R3-02 재고정으로 실측 겹침이 0이 됐다(구 표본 app.js:220 부팅 훅이 ShellHost `.ts` 로
    이양) — 그래서 변이 방향도 뒤집힌다: 구판은 「있는 겹침을 지우면 붉는가」였고, 이제는
    「없는 겹침을 선언으로 만들어내면 붉는가」다. 셋 다 선언≠유도를 민다.
    """
    if mutation == "ghost-member":
        entry = {"member": "frontend/js/ghost.js:999",
                 "axes": ["subscription_listener", "lifecycle_hook"], "reason": "가짜 좌표"}
    elif mutation == "wrong-axes":
        entry = {"member": "frontend/js/app.js:65",
                 "axes": ["dom_static", "state_ring1"], "reason": "실재 좌표·가짜 축"}
    else:  # fabricated — 실재 좌표·실재 축이지만 그 좌표는 한 축에만 측정된다
        entry = {"member": "frontend/js/app.js:65",
                 "axes": ["subscription_listener", "lifecycle_hook"], "reason": "겹침 아님"}
    mutable_document["cross_axis_overlap"] = [entry]
    report = gate.check(mutable_document, REPO_ROOT, metrics=[])
    assert not report.ok, f"`cross_axis_overlap` 의 {mutation} 이 통과했습니다."
    assert "cross_axis_overlap" in _failures(report), _failures(report)


@pytest.mark.parametrize(
    "mutation", ["false-positive-deleted", "false-positive-neutered", "blind-spot-neutered"]
)
def test_coverage_probes_cannot_be_neutered_by_the_ledger(
    mutable_document: dict[str, Any], mutation: str
) -> None:
    """사각·오검 프로브는 원장의 자유 변수가 아니다.

    원장 세 줄(`probe` 를 없는 패턴으로 · `current = 0` · `members = []`)로 뼈대를 없는 것으로
    만들 수 있었고, `false_positive` 는 블록째 지워도 게이트가 초록이었다 — 커밋이 적은
    「blind_spot 과 대칭」이 그 자리에서 성립하지 않았다.
    """
    if mutation == "false-positive-deleted":
        mutable_document["axes"]["lifecycle_factory"].pop("false_positive")
        axis = "lifecycle_factory"
    elif mutation == "false-positive-neutered":
        claim = mutable_document["axes"]["lifecycle_factory"]["false_positive"]
        claim["scope"] = ["nonexistent/**"]
        claim["current"] = 0
        claim["members"] = []
        axis = "lifecycle_factory"
    else:
        claim = mutable_document["axes"]["lifecycle_hook"]["blind_spot"]
        claim["probe"] = {
            "kind": "regex", "pattern": "ZZZNOPE",
            "flavor": "python-re", "granularity": "per-line",
        }
        claim["current"] = 0
        claim["members"] = []
        axis = "lifecycle_hook"
    report = gate.check(mutable_document, REPO_ROOT, axes=[axis], metrics=[])
    assert not report.ok, f"{mutation} 이 통과했습니다."
    text = _failures(report)
    assert "측정 계약이 게이트가 든 지문과 다릅니다" in text, text
    assert axis in text, text


def test_blind_spot_unit_is_required(mutable_document: dict[str, Any]) -> None:
    """술어 3종은 사각 진술에도 예외 없이 걸린다 — `unit` 에 기본값을 두던 구멍."""
    mutable_document["axes"]["subscription_push"]["blind_spot"].pop("unit")
    report = gate.check(mutable_document, REPO_ROOT, axes=["subscription_push"], metrics=[])
    assert not report.ok, "`blind_spot.unit` 누락이 통과했습니다."
    assert "unit" in _failures(report), _failures(report)


@pytest.mark.parametrize("axis_name", ["selftest_frontend_surface", "frontend_static_assets"])
def test_excluded_axis_size_block_cannot_be_deleted(
    mutable_document: dict[str, Any], axis_name: str,
) -> None:
    """크기 블록을 지우면 「소리 나는 제외」가 조용한 유예로 되돌아간다."""
    excluded = next(
        item for item in mutable_document["excluded_axes"]
        if item["axis"] == axis_name
    )
    excluded.pop("size")
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "크기 블록 삭제가 통과했습니다."
    assert axis_name in _failures(report), _failures(report)


def test_static_asset_growth_moves_the_pinned_file_count(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
) -> None:
    """텍스트 프로브가 못 읽는 새 바이너리 자산도 면제 파일 수를 움직여 red다."""
    asset = clone_source / "assets" / "__r3_audit.woff2"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\xff\xfe\x00\x01")

    report = gate.check(document, frontend_tree, axes=[], metrics=[])

    assert not report.ok, "새 바이너리 정적 자산이 명시 제외 안에서 조용히 통과했습니다."
    text = _failures(report)
    assert "frontend_static_assets" in text and "파일 수" in text, text


def test_unoccupied_classifications_is_measured(mutable_document: dict[str, Any]) -> None:
    """부재를 데이터로 적는 습관은 **그 부재를 세야** 성립한다."""
    mutable_document["unoccupied_classifications"] = ["react"]
    report = gate.check(mutable_document, REPO_ROOT, metrics=[])
    assert not report.ok, "거짓 부재 선언이 통과했습니다."
    assert "unoccupied_classifications" in _failures(report), _failures(report)


def test_baseline_sha_is_pinned_to_a_real_coordinate(mutable_document: dict[str, Any]) -> None:
    """40자리 hex 모양만 보면 `\"0\"*40` 도 통과한다 — 재고정은 중앙 판정이 붙는 사건이다."""
    mutable_document["baseline_sha"] = "0" * 40
    report = gate.check(mutable_document, REPO_ROOT, axes=[], metrics=[])
    assert not report.ok, "없는 커밋이 기준선으로 통과했습니다."
    assert "baseline_sha" in _failures(report), _failures(report)


def test_misnested_close_is_refused(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
) -> None:
    """오정렬은 여닫는 **수가 맞아** 불균형 계수에 안 걸린다.

    그런데 브라우저의 관용 복구는 이 파서와 다른 트리를 만들 수 있고, 그러면
    조상 사슬이 거짓이 되어 **접기(컨테이너 귀속)가 함께 거짓**이 된다. 개수가 아니라
    이름을 대조해야 보이는 자리다 — PR #467 리뷰 지적(`block:3`)의 회귀 잠금.
    """
    target = clone_source / "index.html"
    text = target.read_text(encoding="utf-8")
    marker = "</body>"
    assert marker in text, "index.html 에 </body> 가 없습니다 — 앵커를 다시 고르십시오."
    text = text.replace(marker, '<div><span id="misnestZ"></div></span>\n' + marker, 1)
    target.write_text(text, encoding="utf-8")

    report = gate.check(document, frontend_tree, axes=["dom_static"], metrics=[])
    assert not report.ok, "오정렬이 조용히 통과했습니다."
    text_out = _failures(report)
    assert "mismatched-close" in text_out, text_out
    assert "div/span" in text_out, text_out


@pytest.mark.parametrize(
    ("form", "snippet", "expected"),
    [
        ("computed", 'function __n(el){ el["id"] = "sneakyG"; }', "computed-id-assignment"),
        ("wrapped", 'function __n(el){ el.setAttribute(\n  "id",\n  "sneakyH",\n); }', "set-attribute"),
        ("uppercase", 'function __n(el){ el.setAttribute("ID", "sneakyI"); }', "set-attribute"),
    ],
)
def test_id_planting_forms_seven_to_nine_are_seen(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path,
    form: str, snippet: str, expected: str,
) -> None:
    """일곱째~아홉째 형태.

    특히 **줄바꿈된 `setAttribute("id", …)`** 는 원장이 「센다」고 적은 바로 그 형태를 프로브가
    못 넘던 자리다(줄 단위로 돌면 `\\s*` 가 개행을 못 넘는다). 선언과 결과가 어긋난 자리라
    미선언 형태 둘(계산 속성·대문자)과 등급이 다르다.
    """
    target = clone_source / "js" / "theme.js"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n" + snippet + "\n", encoding="utf-8"
    )
    report = gate.check(document, frontend_tree, axes=["dom_js_site"], metrics=[])
    assert not report.ok, f"{form} 형태가 사각에서 안 잡혔습니다."
    text = _failures(report)
    assert "사각이 움직였습니다" in text, text
    assert expected in text, text


# ──────────────────────────────────────────────────────────────────────────
# 음성 — 「주장이 저장소보다 넓다」 세 자리
#
# 셋 다 기계를 넓혀서가 아니라 **주장을 정확히 좁혀서** 닫는다. 이 저장소가 이미 축복한
# 형식이다(`blind_spot`·`false_positive`·`excluded_axes`) — 「전수를 못 본다」를 선언으로
# 정직하게 적는 것이 「전수를 보게 만드는 것」보다 싸고, 거짓말하지 않는다는 점에서 같은 값을 한다.
# 그러려면 선언이 **산문 각주가 아니라 필드**여야 하고, 그 필드가 사라지거나 어긋나면 붉어야 한다.
# ──────────────────────────────────────────────────────────────────────────


def test_probe_form_list_matches_the_extractor(mutable_document: dict[str, Any]) -> None:
    """F1 — 원장이 「여섯 형태」라 적는 동안 추출기는 일곱을 세고 있었다.

    산문만 고치면 다음에 형태가 늘 때 같은 자리로 돌아온다. 목록을 데이터로 두고 게이트가
    추출기와 대조하면 그 어긋남이 조용할 수 없다.
    """
    claim = mutable_document["axes"]["dom_js_site"]["blind_spot"]
    assert "computed-id-assignment" in claim["known_forms"], (
        "일곱째 형태가 원장에 데이터로 없습니다."
    )
    claim["known_forms"] = [
        form for form in claim["known_forms"] if form != "computed-id-assignment"
    ]
    report = gate.check(mutable_document, REPO_ROOT, axes=["dom_js_site"], metrics=[])
    assert not report.ok, "추출기가 세는 형태를 원장이 빠뜨렸는데 통과했습니다."
    text = _failures(report)
    assert "known_forms" in text, text
    assert "computed-id-assignment" in text, text


def test_excluded_surface_counts_files_not_only_content(
    document: dict[str, Any], frontend_tree: Path, clone_source: Path
) -> None:
    """F2 — `export const probe = …` 만 든 selftest 모듈.

    크기 프로브가 **내용**만 세면 이 모듈은 아무것도 보태지 않아 숫자가 안 움직인다. 그런데
    `covers` 는 그 글롭 전체를 제품 트리 피복에서 면제하므로 제외가 소리를 안 낸다.
    파일 **수** 한 줄이면 닫힌다 — 해시 체계를 지을 자리가 아니다.
    """
    module = clone_source / "src" / "selftest" / "__neg_const.js"
    module.write_text("export const probe = { id: 'neg' };\n", encoding="utf-8")
    # `axes=[]` — 제외 행 검사는 축 선택과 무관하게 머리말에서 돈다. 복제 트리에는 `tests/` 가
    # 없어 전체 실행을 쓰면 `verification` 잡음이 섞여 red 의 사유가 흐려진다.
    report = gate.check(document, frontend_tree, axes=[], metrics=[])
    assert not report.ok, "셀 것이 없는 제외 모듈이 조용히 들어왔습니다."
    text = _failures(report)
    assert "selftest_frontend_surface" in text, text
    assert "파일" in text, text


def test_narrow_axis_states_its_limit_with_an_owner(
    mutable_document: dict[str, Any]
) -> None:
    """F3 — 제품보다 좁은 scope 는 **그렇게 적혀 있어야** 한다.

    `subscription_push` 가 재는 것은 「합성 루트·화면 파일 안의 스냅샷 구독 등록」이지
    「제품 전체의 구독」이 아니다 — overlay engine 구독과 store 의 구독 **구현**은 밖이다.
    scope 를 넓히는 대신 그 차이를 소유자와 함께 선언한다 — 선언이 사라지면 축이 다시 자기
    범위를 넘어 주장하게 되므로 그 자리가 붉어야 한다.

    소유자가 R2-04 에서 R4-02 로 옮겼다. 종전 한계문이 「그 질문을 여는 슬라이스가 범위를
    정해야 한다」를 예고했고, 편집기·작업대의 마지막 화면 소유 `Bridge.onPush` 를 걷어
    legacy scope 안 측정을 0 으로 만드는 슬라이스가 정확히 그 슬라이스다.
    """
    axis = mutable_document["axes"]["subscription_push"]
    limitation = axis["scope_limitation"]
    assert limitation["owner"] == "R4-02 #415", (
        "좁은 scope 의 소유자가 사라졌습니다 — 소유자 없는 한계는 유예로 읽힙니다."
    )
    assert "modal.js" in limitation["statement"] or "제품" in limitation["statement"], (
        "한계 진술이 무엇을 못 보는지 말하지 않습니다."
    )
    axis.pop("scope_limitation")
    report = gate.check(mutable_document, REPO_ROOT, axes=["subscription_push"], metrics=[])
    assert not report.ok, "좁은 scope 가 한계 선언 없이 통과했습니다."
    text = _failures(report)
    assert "scope_limitation" in text, text
    assert "subscription_push" in text, text
