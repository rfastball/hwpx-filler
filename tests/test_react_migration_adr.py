"""React 전환 ADR(`docs/REACT_MIGRATION_DECISIONS.md`)이 조용히 낡지 않게 지킨다 (#401).

ADR 은 산문이라 기계가 볼 수 없는 부분이 크다 — 근거의 참거짓, 문장의 품질은 리뷰 몫이다.
여기서 겨누는 것은 **선언과 결과가 갈리는 자리**다. 이 저장소가 반복해 만난 결함류는
「선언(주석·계약·문서 행)은 살고 결과는 죽는다」이고, 결정 원장은 그 결함류의 표적이 크다:

- 상위 원장(#394)에 결정이 하나 늘면 ADR 은 **초록인 채** 그 항을 놓친다.
- 문서 지도가 「부분 대체」라 적는 동안 대상 문서 머리말은 「유효 결정」인 채 남을 수 있다.
- ADR 이 적은 수(「직접 브리지 21」)와 게이트가 실제로 세는 수(23)가 갈려도 아무도 붉어지지
  않는다 — 실제로 오늘 `frontend/js/bridge.js` 머리말이 그렇게 낡아 있다.

그래서 다섯 술어는 **이름이 아니라 결과**를 센다. 그리고 각 술어에는 합성 fixture 음성 대조
짝이 있다 — 「빠뜨리면 붉어진다」를 먼저 증명하지 않은 게이트는 초록의 의미가 없다.

**이 게이트가 하지 않는 것**: R1 산출물 TOML 두 개의 **존재**는 단언하지 않는다. #401 이 먼저
착지하고 #402·#403 이 뒤따르므로, 존재를 단언하면 중간 master 에서 거짓 실패가 나
R-D12(각 병합 시점의 master 는 실행·검증·revert 가능)를 이 게이트가 깬다. 존재 단언은 각
산출물 자신의 게이트가 진다.
"""

from __future__ import annotations

import re

import pytest

from _web_source import REPO_ROOT, SOURCE_JS_DIR

DOCS = REPO_ROOT / "docs"
ADR_PATH = DOCS / "REACT_MIGRATION_DECISIONS.md"
README_PATH = DOCS / "README.md"
PRESERVATION_PATH = DOCS / "WEB_RENDER_PRESERVATION.md"
UI_CONTRACT_PATH = DOCS / "UI_CONTRACT.md"
# 물리 source 루트는 `_web_source` 가 단일 소유한다 — 여기서 다시 유도하지 않는다
# (`test_web_source_role.py` 가 강제).
BRIDGE_JS_PATH = SOURCE_JS_DIR / "bridge.js"

# 상위 결정 원장의 항 수. 출처: #394 본문 「결정 원장」 R-D01~R-D17, `73473de` 시점.
# 늘면 이 상수가 시끄럽게 실패한다 — ADR 이 새 항을 조용히 놓치는 것보다 낫다.
DECISION_COUNT = 17
ALL_DECISIONS = frozenset(f"R-D{n:02d}" for n in range(1, DECISION_COUNT + 1))

# `R1-ARTIFACT-LAYOUT:v1`(#395)이 동결한 R1 3산출물. 지도가 셋을 다 언급해야 한다.
R1_ARTIFACTS = (
    "REACT_MIGRATION_DECISIONS.md",
    "react_ownership_inventory.toml",
    "react_verification_ledger.toml",
)

# #401 본문의 대문자 분류값을 소문자로 승계한 어휘. #402 TOML 이 이 철자를 enum 으로 쓴다.
CLASSIFICATION_VOCABULARY = (
    "react",
    "python_product",
    "host",
    "retire",
    "p_review_required",
)

# ADR 이 이름 지은 세 집합. 하나의 수로 적으면 게이트가 세는 값과 갈린다.
SET_NAMES = ("산문 정본 집합", "Python 도달 집합", "게이트 대조 집합")


# --------------------------------------------------------------------------- #
# 추출기 — 전부 순수 함수라 음성 대조가 합성 사본을 그대로 먹인다.
# --------------------------------------------------------------------------- #

_ADR_HEADING = re.compile(r"^### (ADR-\d{2})\b", re.MULTILINE)
_TRACE_LINE = re.compile(r"^\*\*추적:\*\*(.*)$", re.MULTILINE)
_DECISION_TOKEN = re.compile(r"R-D\d{2}")


def _adr_entries(adr: str) -> dict[str, str]:
    """`### ADR-nn` 제목마다 다음 제목 직전까지의 본문을 자른다."""
    starts = [(m.group(1), m.start()) for m in _ADR_HEADING.finditer(adr)]
    entries: dict[str, str] = {}
    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(adr)
        entries[name] = adr[start:end]
    return entries


def _traced_decisions(adr: str) -> dict[str, set[str]]:
    """항목 → 그 항목이 승계 선언한 R-D 번호 집합. 추적 줄이 없으면 빈 집합."""
    traced: dict[str, set[str]] = {}
    for name, body in _adr_entries(adr).items():
        tokens: set[str] = set()
        for match in _TRACE_LINE.finditer(body):
            tokens.update(_DECISION_TOKEN.findall(match.group(1)))
        traced[name] = tokens
    return traced


def _header_field(document: str, label: str) -> str | None:
    """머리말 인용 블록의 `> **라벨:** 값` 한 줄을 값으로 돌려준다."""
    pattern = re.compile(rf"^> \*\*{re.escape(label)}:\*\*\s*(.+)$", re.MULTILINE)
    match = pattern.search(document)
    return match.group(1).strip() if match else None


def _map_row(readme: str, link_target: str) -> str | None:
    """문서 지도에서 그 파일을 가리키는 표 행 전체를 돌려준다."""
    for line in readme.splitlines():
        if line.startswith("|") and f"]({link_target})" in line:
            return line
    return None


def _row_status(row: str | None) -> str | None:
    """`| 문서 | 상태 | 유효 범위 |` 행의 두 번째 칸."""
    if row is None:
        return None
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    return cells[1] if len(cells) >= 2 else None


def _recorded_set_sizes(adr: str) -> dict[str, int]:
    """ADR 의 세 집합 표에 적힌 크기."""
    recorded: dict[str, int] = {}
    for line in adr.splitlines():
        match = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(\d+)\s*\|", line)
        if match and match.group(1) in SET_NAMES:
            recorded[match.group(1)] = int(match.group(2))
    return recorded


def _prose_bridge_methods(ui_contract: str) -> set[str]:
    """UI 계약 「직접 브리지 경로」 절이 산문으로 열거하는 메서드 이름."""
    lines = ui_contract.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("- **직접 브리지 경로:**")]
    if not starts:
        return set()
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("###")), len(lines))
    block = "\n".join(lines[start:end])
    return {
        name
        for name in re.findall(r"`([^`]+)`", block)
        if re.fullmatch(r"[a-z][a-z0-9_]*", name)
    }


def _gate_bridge_methods(bridge_js: str) -> set[str]:
    """`test_architecture.py` 의 직접 브리지 게이트가 실제로 대조하는 집합과 같은 추출."""
    return set(re.findall(r"\bapi\.(\w+)", bridge_js)) - {"initial", "dispatch"}


def _python_reachable_methods() -> set[str]:
    """`WebFrontend` 의 실제 공개 표면 — 웹에서 부를 수 있는 전부."""
    from hwpxfiller.webapp.app import WebFrontend

    return {
        name
        for name in dir(WebFrontend)
        if not name.startswith("_") and callable(getattr(WebFrontend, name))
    }


def _measured_set_sizes() -> dict[str, int]:
    return {
        "산문 정본 집합": len(_prose_bridge_methods(UI_CONTRACT_PATH.read_text(encoding="utf-8"))),
        "Python 도달 집합": len(_python_reachable_methods()),
        "게이트 대조 집합": len(_gate_bridge_methods(BRIDGE_JS_PATH.read_text(encoding="utf-8"))),
    }


@pytest.fixture(scope="module")
def adr() -> str:
    return ADR_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 술어 1 — 상위 결정 원장 R-D01~R-D17 과의 1:1 추적
# --------------------------------------------------------------------------- #


def test_every_parent_decision_has_an_owning_adr_entry(adr: str) -> None:
    """R-D 17항 각각이 어느 ADR 항목엔가 `**추적:**` 으로 주인을 갖는다.

    주인 없는 결정은 ADR 이 「1:1 추적」이라 선언해 놓고 실제로는 부분집합만 옮긴 상태다 —
    R1-99 가 그것을 산문 대조로 잡아내야 하는 상황을 만들지 않는다.
    """
    traced = _traced_decisions(adr)
    assert traced, "ADR 에서 `### ADR-nn` 항목을 하나도 찾지 못했습니다(추출 회귀)."
    covered: set[str] = set().union(*traced.values())
    missing = sorted(ALL_DECISIONS - covered)
    assert not missing, (
        f"ADR 어느 항목도 승계하지 않은 상위 결정: {', '.join(missing)} — "
        f"#394 결정 원장은 {DECISION_COUNT}항이고 ADR 은 1:1 추적을 선언한다."
    )


def test_no_adr_entry_traces_an_unknown_decision(adr: str) -> None:
    """역방향 — 존재하지 않는 R-D 번호를 승계 선언하지 않는다(오타·유령 추적 차단)."""
    traced = _traced_decisions(adr)
    unknown = sorted(set().union(*traced.values()) - ALL_DECISIONS)
    assert not unknown, (
        f"#394 결정 원장에 없는 번호를 추적합니다: {', '.join(unknown)} — "
        f"오늘의 원장은 R-D01~R-D{DECISION_COUNT:02d} 다."
    )


def test_every_adr_entry_declares_its_trace(adr: str) -> None:
    """추적 줄이 없는 항목이 없다 — 있으면 그 항목은 어느 결정의 후계인지 모른다."""
    untraced = sorted(name for name, tokens in _traced_decisions(adr).items() if not tokens)
    assert not untraced, (
        f"`**추적:**` 줄이 없거나 비어 있는 ADR 항목: {', '.join(untraced)}"
    )


def test_the_trace_detector_notices_a_dropped_decision(adr: str) -> None:
    """음성 대조 — 추적에서 R-D 하나를 빼면 검출된다."""
    victim = "R-D17"
    tampered = adr.replace(f"**추적:** {victim}", "**추적:** R-D04")
    assert tampered != adr, "합성 대상 추적 줄을 찾지 못했습니다(fixture 회귀)."
    covered: set[str] = set().union(*_traced_decisions(tampered).values())
    assert victim not in covered, "추적 줄에서 결정을 빼도 추출기가 여전히 본다 — 판별력 0."


# --------------------------------------------------------------------------- #
# 술어 2 — 뒤집히는 문서의 머리말이 실제로 전환됐다
# --------------------------------------------------------------------------- #


def test_adr_claims_succession_and_the_superseded_header_agrees(adr: str) -> None:
    """ADR 이 승계를 선언하는 것과 대상 문서가 실제로 「부분 대체」인 것을 **함께** 본다.

    한쪽만 고치면 붉어진다. 이 저장소에서 조용히 갈리는 전형이 이 짝이다 — 새 결정 문서는
    「내가 대체했다」고 적고, 대체당한 문서는 「유효 결정」인 채로 계속 정본 행세를 한다.
    """
    assert "WEB_RENDER_PRESERVATION.md" in adr, (
        "ADR 이 승계 대상(웹 재렌더 보존)을 명시하지 않습니다."
    )

    preservation = PRESERVATION_PATH.read_text(encoding="utf-8")
    status = _header_field(preservation, "문서 상태")
    assert status == "부분 대체", (
        f"WEB_RENDER_PRESERVATION.md 머리말 상태가 '{status}' 입니다 — ADR-01 이 그 결정을 "
        "뒤집었으므로 '부분 대체' 여야 합니다."
    )

    successor = _header_field(preservation, "후속 정본") or ""
    assert "REACT_MIGRATION_DECISIONS.md" in successor, (
        "WEB_RENDER_PRESERVATION.md 의 후속 정본이 React 전환 ADR 을 지목하지 않습니다: "
        f"{successor!r}"
    )


def test_the_header_detector_notices_a_stale_status() -> None:
    """음성 대조 — 머리말이 전환되지 않은 사본에서 검출된다."""
    stale = PRESERVATION_PATH.read_text(encoding="utf-8").replace(
        "> **문서 상태:** 부분 대체", "> **문서 상태:** 유효 결정", 1
    )
    assert _header_field(stale, "문서 상태") == "유효 결정", (
        "머리말 상태를 되돌려도 추출기가 새 값을 본다 — 판별력 0."
    )


def test_the_successor_detector_notices_a_missing_pointer() -> None:
    """음성 대조 — 후속 정본이 ADR 을 지목하지 않는 사본에서 검출된다."""
    preservation = PRESERVATION_PATH.read_text(encoding="utf-8")
    stripped = re.sub(
        r"^> \*\*후속 정본:\*\*.*$",
        "> **후속 정본:** 구현은 `frontend/js/preserve.js`",
        preservation,
        count=1,
        flags=re.MULTILINE,
    )
    assert "REACT_MIGRATION_DECISIONS.md" not in (_header_field(stripped, "후속 정본") or ""), (
        "후속 정본 포인터를 지워도 추출기가 여전히 본다 — 판별력 0."
    )


# --------------------------------------------------------------------------- #
# 술어 3 — 문서 지도가 3산출물을 등재하고 상태 전환을 반영했다
# --------------------------------------------------------------------------- #


def test_the_document_map_registers_every_r1_artifact(readme: str) -> None:
    """지도에 없는 산출물은 저장소에서 발견되지 않는다 — 지도가 유일한 입구다.

    **존재는 단언하지 않는다.** #402·#403 이 아직 착지하지 않은 중간 master 에서 존재를 요구하면
    이 게이트가 R-D12(각 병합 시점 master 의 실행·검증 가능)를 깬다.
    """
    missing = [name for name in R1_ARTIFACTS if name not in readme]
    assert not missing, (
        f"문서 지도(docs/README.md)에 등재되지 않은 R1 산출물: {', '.join(missing)}"
    )


def test_the_document_map_reflects_the_superseded_status(readme: str) -> None:
    """지도의 웹 재렌더 보존 행이 「부분 대체」다 — 머리말과 지도가 함께 움직인다."""
    row = _map_row(readme, "WEB_RENDER_PRESERVATION.md")
    assert row is not None, "문서 지도에서 웹 재렌더 보존 행을 찾지 못했습니다."
    assert _row_status(row) == "부분 대체", (
        f"지도의 웹 재렌더 보존 행 상태가 '{_row_status(row)}' 입니다 — '부분 대체' 여야 합니다."
    )


def test_the_map_detectors_notice_a_dropped_row(readme: str) -> None:
    """음성 대조 — 등재를 빼거나 상태를 되돌린 사본에서 각각 검출된다."""
    without_ledger = readme.replace("react_verification_ledger.toml", "(삭제됨)")
    assert "react_verification_ledger.toml" not in without_ledger, (
        "산출물 등재를 지워도 검출되지 않는다 — 판별력 0."
    )

    row = _map_row(readme, "WEB_RENDER_PRESERVATION.md")
    assert row is not None
    reverted = readme.replace(row, row.replace("| 부분 대체 |", "| 유효 결정 |", 1))
    assert _row_status(_map_row(reverted, "WEB_RENDER_PRESERVATION.md")) == "유효 결정", (
        "지도 행 상태를 되돌려도 추출기가 새 값을 본다 — 판별력 0."
    )


# --------------------------------------------------------------------------- #
# 술어 4 — 분류 어휘 5종의 철자
# --------------------------------------------------------------------------- #


def test_adr_defines_the_classification_vocabulary_verbatim(adr: str) -> None:
    """#402 TOML 이 enum 으로 쓸 철자가 ADR 에 정확히 그대로 있다.

    철자가 갈리면 두 문서가 각자 초록인 채 서로 다른 어휘를 쓴다 — 분류 정본이 둘이 된다.
    """
    missing = [value for value in CLASSIFICATION_VOCABULARY if f"`{value}`" not in adr]
    assert not missing, (
        f"ADR 에 분류 어휘가 그 철자로 정의되지 않았습니다: {', '.join(missing)}"
    )


def test_the_vocabulary_detector_notices_a_respelled_value(adr: str) -> None:
    """음성 대조 — 철자를 바꾼 사본에서 검출된다."""
    tampered = adr.replace("`p_review_required`", "`pReviewRequired`")
    assert tampered != adr, "합성 대상 어휘를 찾지 못했습니다(fixture 회귀)."
    assert "`p_review_required`" not in tampered, "철자를 바꿔도 검출되지 않는다 — 판별력 0."


# --------------------------------------------------------------------------- #
# 술어 5 — 「직접 브리지」 세 집합을 저장소에서 재계산해 대조
# --------------------------------------------------------------------------- #


def test_adr_records_three_distinct_bridge_sets(adr: str) -> None:
    """세 집합이 각각 이름과 크기로 등장한다 — 단일 수로 적으면 게이트와 갈린다."""
    recorded = _recorded_set_sizes(adr)
    missing = [name for name in SET_NAMES if name not in recorded]
    assert not missing, (
        f"ADR 이 이름과 크기로 적지 않은 직접 브리지 집합: {', '.join(missing)}"
    )
    assert len(set(recorded.values())) == 3, (
        f"세 집합의 크기가 서로 달라야 합니다(각각 다른 것을 세므로): {recorded}"
    )


def test_recorded_bridge_set_sizes_match_the_repository(adr: str) -> None:
    """ADR 이 적은 세 수를 저장소에서 **재계산해** 대조한다.

    정적 상수를 믿지 않는다. 오늘 `frontend/js/bridge.js:2` 머리말이 이 표면을 낡은 분해로
    적고 있는 것이 실물 표본이다 — 선언은 살아 있고 결과는 이미 갈렸다.
    """
    recorded = _recorded_set_sizes(adr)
    measured = _measured_set_sizes()
    assert all(measured.values()), f"집합 추출이 비었습니다(추출 회귀): {measured}"
    mismatched = {
        name: (recorded.get(name), measured[name])
        for name in SET_NAMES
        if recorded.get(name) != measured[name]
    }
    assert not mismatched, (
        "ADR 의 직접 브리지 집합 크기가 저장소 실측과 다릅니다 "
        f"(기재 → 실측): {mismatched} — ADR 을 갱신하거나 표면 변경을 되돌리세요."
    )


def test_the_three_sets_really_are_different_sets() -> None:
    """세 집합이 이름만 다른 같은 것이 아님을 실제 원소로 보인다.

    ADR 의 주장(「세 개의 다른 집합이다」)이 오늘 참인지를 여기서 확인한다 — 크기 대조만으로는
    우연히 같은 수가 나올 때 침묵한다.
    """
    prose = _prose_bridge_methods(UI_CONTRACT_PATH.read_text(encoding="utf-8"))
    gate = _gate_bridge_methods(BRIDGE_JS_PATH.read_text(encoding="utf-8"))
    python = _python_reachable_methods()

    assert gate - python, (
        "게이트 대조 집합이 Python 공개 표면의 부분집합이 됐습니다 — "
        "ADR 이 적은 '두 여분은 WebFrontend 메서드가 아니다' 가 더 이상 참이 아닙니다."
    )
    assert python - prose - {"initial", "dispatch"}, (
        "Python 도달 집합이 산문 정본 + dispatch 2개로 소진됐습니다 — "
        "ADR-05 가 실물로 든 단방향 게이트 표본(close_guard_state)이 사라졌습니다."
    )
    assert prose <= python, (
        f"산문 정본이 실재하지 않는 메서드를 열거합니다: {sorted(prose - python)}"
    )


def test_the_size_detector_notices_a_stale_number(adr: str) -> None:
    """음성 대조 — ADR 의 기재 수를 하나 틀리게 만든 사본에서 검출된다."""
    recorded = _recorded_set_sizes(adr)
    victim = "게이트 대조 집합"
    tampered = adr.replace(f"| **{victim}** | {recorded[victim]} |", f"| **{victim}** | 21 |")
    assert tampered != adr, "합성 대상 표 행을 찾지 못했습니다(fixture 회귀)."
    assert _recorded_set_sizes(tampered)[victim] != _measured_set_sizes()[victim], (
        "기재 수를 틀리게 만들어도 대조가 통과한다 — 판별력 0."
    )
