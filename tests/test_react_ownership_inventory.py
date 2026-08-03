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

## 먼저 인정하는 것

이 슬라이스는 **실재 유령으로 red 를 낼 수 없다**. 원장과 게이트가 같은 PR 에서 태어나므로
병합 시점의 원장은 정의상 완전하고 그때 게이트는 반드시 초록이다. 유령 대조(N10)는 원장 변이다.
그리고 `M − C = ∅` 은 저장소에 대해서가 아니라 **선언된 축의 추출기가 본 것**에 대해 0이다 —
그 문장은 원장의 `scope_statement` 에 데이터로 들어 있다.
"""

from __future__ import annotations

import copy
import importlib.util
import shutil
import sys
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
    """복제 트리의 **저장소 루트** — 정적 소스에서 글꼴만 뺀다(5.4 MB).

    저장소 변이는 실 저장소를 절대 건드리지 않는다. `axes=[…]` 인자로 해당 축만 검사해
    없는 파일 때문에 무관한 축이 죽지 않게 한다 — 그 인자가 필요한 이유가 여기다.

    물리 경로 이름은 :mod:`_web_source` 가 단일 출처다 — 여기서 다시 조립하면 소스 트리를
    옮기는 날 이 게이트만 옛 자리를 보며 조용히 산다.
    """
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copytree(
        SOURCE_ROOT,
        root / SOURCE_ROOT.name,
        ignore=shutil.ignore_patterns("fonts"),
    )
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
    assert set(report.axes) == set(document["axes"]), "선언한 축과 측정한 축이 다릅니다."


def test_scope_statement_and_exclusions_are_data_not_prose(document: dict[str, Any]) -> None:
    """「미분류 0」의 범위와 제외 축은 산문 각주가 아니라 머리말 데이터여야 한다."""
    assert document["scope_statement"].strip(), "scope_statement 가 비었습니다."
    assert document.get("repo_wide_metrics") == [], (
        "저장소 전수 scope 계측이 생겼습니다 — 고정 수치가 아니라 base_sha 앵커 + 정당화된 "
        "delta 로 적어야 합니다."
    )
    excluded = {item["axis"]: item for item in document["excluded_axes"]}
    assert "js_planted_data_attrs" in excluded, (
        "JS 가 심는 data-* 축의 **명시 제외**가 사라졌습니다 — 조용한 유예가 되면 「미분류 0」이 "
        "거짓말이 됩니다."
    )
    assert excluded["js_planted_data_attrs"]["owner"], "제외 축에 소유자가 없습니다."


#: 복제 트리에서 잴 수 있는 축 — Python import 두 축(`state_snapshot_channel`·`state_ring1`)은
#: `src/` 를 복사하지 않으므로 뺀다. 없는 파일 때문에 무관한 축이 죽으면 그 음성 대조는 자기가
#: 겨눈 좌표를 증명하지 못한다.
CLONE_AXES = [
    "dom_static", "dom_data_attr", "dom_js_site", "state_js_module",
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
    target = clone_source / "js" / "sheet_picker.js"
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if "innerHTML" not in line or "=" not in line]
    assert len(kept) == len(lines) - 1, "sheet_picker.js 의 대입이 하나가 아닙니다 — 변이를 다시 겨눠야 합니다."
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
    target = clone_source / "js" / "screens" / "workbench.js"
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() != "let wired = false;"]
    assert len(kept) == len(lines) - 1, "workbench.js 의 `let wired` 좌표가 바뀌었습니다."
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
    """N9 — 노드 행 하나를 지우면 그 멤버가 미분류로 나온다."""
    victim = next(
        node for node in mutable_document["node"] if node["id"] == "state/app-shell"
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
        node for node in mutable_document["node"] if node["id"] == "state/app-shell"
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
