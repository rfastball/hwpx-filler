"""React 전환 ADR(`docs/REACT_MIGRATION_DECISIONS.md`)이 조용히 낡지 않게 지킨다 (#401).

ADR 은 산문이라 기계가 볼 수 없는 부분이 크다 — 근거의 참거짓, 문장의 품질은 리뷰 몫이다.
여기서 겨누는 것은 **선언과 결과가 갈리는 자리**다. 이 저장소가 반복해 만난 결함류는
「선언(주석·계약·문서 행)은 살고 결과는 죽는다」이고, 결정 원장은 그 결함류의 표적이 크다:

- 상위 원장(#394)에 결정이 하나 늘면 ADR 은 **초록인 채** 그 항을 놓친다.
- 문서 지도가 「부분 대체」라 적는 동안 대상 문서 머리말은 「유효 결정」인 채 남을 수 있다.
- ADR 이 적은 수(「직접 브리지 21」)와 게이트가 실제로 세는 수(23)가 갈려도 아무도 붉어지지
  않는다 — 실제로 오늘 `frontend/js/bridge.js` 머리말이 그렇게 낡아 있다.

그래서 다섯 술어는 **이름이 아니라 결과**를 센다. 그리고 각 술어에는 음성 대조 짝이 있다 —
「빠뜨리면 붉어진다」를 먼저 증명하지 않은 게이트는 초록의 의미가 없다.

**음성 대조의 변형은 최소여야 한다.** 전역 치환으로 만들면 「표에서만 사라지고 산문에는 남았다」
같은 실제 구멍을 만들지 못해, 대조가 자기가 증명하려던 판별력을 스스로 감춘다. 이 파일의 초판이
바로 그 함정에 빠졌었다(리뷰 지적, PR #456).

**이 게이트가 하지 않는 것** — 셋:

1. R1 산출물 TOML 두 개의 **존재**는 단언하지 않는다. #401 이 먼저 착지하고 #402·#403 이
   뒤따르므로, 존재를 단언하면 중간 master 에서 거짓 실패가 나 R-D12(각 병합 시점의 master 는
   실행·검증·revert 가능)를 이 게이트가 깬다. 존재 단언은 각 산출물 자신의 게이트가 진다.
2. #394 본문이 **R-D18 을 얻는 것**은 감지하지 못한다 — `DECISION_COUNT` 옆 주석이 그 결손과
   소유(#457)를 적는다.
3. 브리지 표면의 크기가 **자라는 것**은 위반으로 보지 않는다. 기준선 수치는 동결이고, HEAD 에서
   보는 것은 관계뿐이다.

**한 단언만 ADR 범위를 넘는다** — `test_every_mapped_document_header_agrees_with_the_map`.
결함류가 넘기 때문이다. 「문서가 스스로에 대해 주장하는 것과 정본 지도가 말하는 것이 갈린다」는
한 파일의 사고가 아니라서, 한 짝만 지키면 다음 문서에서 같은 모양으로 돌아온다.
"""

from __future__ import annotations

import json
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
#
# **이 상수는 상위 원장의 성장을 감지하지 못한다.** #394 가 R-D18 을 얻어도 저장소는 그것을
# 모른다 — 이슈 본문은 저장소 밖이고, 사본을 들이면 그 사본이 다시 조용히 갈린다. 상수의
# 실제 역할은 ADR 과 게이트를 서로 묶는 **자물쇠**다: ADR 이 R-D18 을 추적하기 시작하면
# 상수를 올리지 않는 한 붉어지고, 상수를 올리면 ADR 이 그 항의 주인을 대야 붉은색이 풀린다.
# 상위 성장의 감지는 단계 개방 시 재실측(ADR-09)과 R1-99(#400) 재대조가 진다. 결손은 #457.
DECISION_COUNT = 17
ALL_DECISIONS = frozenset(f"R-D{n:02d}" for n in range(1, DECISION_COUNT + 1))

# `R1-ARTIFACT-LAYOUT:v1`(#395)이 동결한 R1 3산출물. 지도의 **표에** 셋이 다 있어야 한다.
R1_ARTIFACTS = (
    "REACT_MIGRATION_DECISIONS.md",
    "react_ownership_inventory.toml",
    "react_verification_ledger.toml",
)

# #401 본문의 대문자 분류값을 소문자로 승계한 어휘. #402 TOML 이 이 철자를 enum 으로 쓴다.
CLASSIFICATION_VOCABULARY = frozenset(
    {"react", "python_product", "host", "retire", "p_review_required"}
)

# ADR 이 이름 지은 세 집합. 하나의 수로 적으면 게이트가 세는 값과 갈린다.
SET_NAMES = ("산문 정본 집합", "Python 도달 집합", "게이트 대조 집합")

# 지도↔머리말 상태 일치의 **명시 면제**. 이유와 소유를 함께 적는다 — 조용한 스킵 금지.
# 목록이 실제 불일치 집합과 정확히 같아야 하므로, 고쳐지면 게이트가 「면제를 지우라」고 말한다.
HEADER_STATUS_EXEMPTIONS = {
    # 2026-07-29 동결 문서라 머리말이 없다. 신설은 #401 의 write set 밖(#458 소유).
    "archive/DATA_FIRST_INTEGRATION_MAP.md": "동결 문서 — 머리말 신설은 #458",
}

# `73473de` 실측 **동결값**이다. R5 가 delta 를 재는 기준선이라 HEAD 를 좇지 않는다 —
# 좇게 하면 브리지 표면이 바뀔 때마다 기준선이 덮어써져 비교 대상 자체가 사라진다.
# HEAD 에서 지켜야 하는 것은 이 수가 아니라 **세 집합이 서로 다르다**는 관계다(아래 술어 5).
BASELINE_BRIDGE_SET_SIZES = {"산문 정본 집합": 21, "Python 도달 집합": 24, "게이트 대조 집합": 23}


# --------------------------------------------------------------------------- #
# 추출기 — 전부 순수 함수라 음성 대조가 합성 사본을 그대로 먹인다.
# --------------------------------------------------------------------------- #

_ADR_HEADING = re.compile(r"^### (ADR-\d{2})\b", re.MULTILINE)
_TRACE_LINE = re.compile(r"^\*\*추적:\*\*(.*)$", re.MULTILINE)
_REFERENCE_LINE = re.compile(r"^\*\*참조:\*\*(.*)$", re.MULTILINE)
_DECISION_TOKEN = re.compile(r"R-D\d{2}")


def _adr_entries(adr: str) -> dict[str, str]:
    """`### ADR-nn` 제목마다 다음 제목 직전까지의 본문을 자른다."""
    starts = [(m.group(1), m.start()) for m in _ADR_HEADING.finditer(adr)]
    entries: dict[str, str] = {}
    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(adr)
        entries[name] = adr[start:end]
    return entries


def _decision_lines(adr: str, pattern: re.Pattern[str]) -> dict[str, set[str]]:
    """항목 → 그 줄이 적은 R-D 번호 집합. 줄이 없으면 빈 집합."""
    found: dict[str, set[str]] = {}
    for name, body in _adr_entries(adr).items():
        tokens: set[str] = set()
        for match in pattern.finditer(body):
            tokens.update(_DECISION_TOKEN.findall(match.group(1)))
        found[name] = tokens
    return found


def _traced_decisions(adr: str) -> dict[str, set[str]]:
    """항목 → 그 항목이 **소유**를 선언한 R-D 번호 집합."""
    return _decision_lines(adr, _TRACE_LINE)


def _referenced_decisions(adr: str) -> dict[str, set[str]]:
    """항목 → 소유하지 않고 **참조**만 하는 R-D 번호 집합."""
    return _decision_lines(adr, _REFERENCE_LINE)


def _owners(adr: str) -> dict[str, list[str]]:
    """R-D 번호 → 그것을 소유한다고 선언한 항목들. 정상이면 항목 리스트 길이가 1."""
    owners: dict[str, list[str]] = {}
    for name, tokens in sorted(_traced_decisions(adr).items()):
        for token in sorted(tokens):
            owners.setdefault(token, []).append(name)
    return owners


def _section(document: str, heading: str) -> str:
    """`## 제목` 부터 다음 `## ` 직전까지. 없으면 빈 문자열."""
    lines = document.splitlines()
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def _table_rows(section: str) -> list[list[str]]:
    """마크다운 표의 **데이터 행**만 셀 리스트로. 머리행·구분선은 뺀다.

    「그 문자열이 파일 어딘가에 있다」가 아니라 「그 표의 행으로 있다」를 묻기 위한 것이다.
    산문에 남은 언급이 표에서 사라진 항목을 가려 주는 것이 이 저장소의 반복 결함류다.
    """
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(cell and set(cell) <= {"-", ":"} for cell in cells):  # 구분선
            if rows:
                rows.pop()  # 바로 앞 행은 머리행이었다 (한 절에 표가 여럿이어도 맞다)
            continue
        rows.append(cells)
    return rows


def _map_table_rows(readme: str) -> list[list[str]]:
    """문서 지도의 두 표(현재 정본 · 결정 기록) 데이터 행 전부."""
    return _table_rows(_section(readme, "현재 정본")) + _table_rows(_section(readme, "결정 기록"))


def _declared_vocabulary(adr: str) -> set[str]:
    """ADR 「권위 분류 어휘」 **표의 첫 칸**에 backtick 으로 정의된 값."""
    values: set[str] = set()
    for row in _table_rows(_section(adr, "권위 분류 어휘")):
        match = re.fullmatch(r"`([a-z_]+)`", row[0])
        if match:
            values.add(match.group(1))
    return values


def _header_field(document: str, label: str) -> str | None:
    """머리말 인용 블록의 `> **라벨:** 값` 한 줄을 값으로 돌려준다."""
    pattern = re.compile(rf"^> \*\*{re.escape(label)}:\*\*\s*(.+)$", re.MULTILINE)
    match = pattern.search(document)
    return match.group(1).strip() if match else None


def _status_token(declared: str) -> str:
    """`유효 결정 (**판정 완결 …**)` 처럼 주석이 붙은 상태에서 상태어만 뽑는다."""
    return declared.split(" (", 1)[0].strip()


def _map_linked_documents(readme: str) -> dict[str, str]:
    """문서 지도가 **링크로** 가리키는 `.md` → 지도가 부여한 상태.

    「현재 정본」 표에는 상태 칸이 없다 — 절 이름 자체가 상태다.
    """
    linked: dict[str, str] = {}
    for section, implied in (("현재 정본", "현재 정본"), ("결정 기록", None), ("역사·동결 자료", None)):
        for row in _table_rows(_section(readme, section)):
            match = re.search(r"\]\(([^)]+\.md)\)", row[0])
            if not match:
                continue
            linked[match.group(1)] = implied or (row[1] if len(row) > 1 else "")
    return linked


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


@pytest.fixture(scope="module")
def adr() -> str:
    return ADR_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 술어 1 — 상위 결정 원장 R-D01~R-D17 과의 1:1 추적 (소유는 정확히 하나)
# --------------------------------------------------------------------------- #


def test_every_parent_decision_has_exactly_one_owning_adr_entry(adr: str) -> None:
    """R-D 17항 각각의 주인이 **정확히 하나**다 — 없어도, 둘이어도 붉어진다.

    「1:1 추적」은 전사(全射)만으로는 참이 아니다. 두 항목이 같은 결정을 주장하면 나중에 한쪽만
    고쳐졌을 때 어느 쪽이 정본인지 말할 수 없고, 그 상태로도 커버리지 검사는 초록이다 —
    선언은 살고 결과는 죽는 그 자리다. 초판이 실제로 그랬다: R-D05 를 ADR-03·ADR-04 가,
    R-D11 을 ADR-09·ADR-12 가 함께 주장했고 게이트는 침묵했다(리뷰 지적, PR #456).
    """
    entries = _adr_entries(adr)
    assert entries, "ADR 에서 `### ADR-nn` 항목을 하나도 찾지 못했습니다(추출 회귀)."
    owners = _owners(adr)
    orphaned = sorted(ALL_DECISIONS - set(owners))
    assert not orphaned, (
        f"주인 없는 상위 결정: {', '.join(orphaned)} — "
        f"#394 결정 원장은 {DECISION_COUNT}항이고 ADR 은 1:1 추적을 선언한다."
    )
    shared = {token: names for token, names in owners.items() if len(names) > 1}
    assert not shared, (
        f"두 항목 이상이 같은 결정을 소유한다고 주장합니다: {shared} — "
        "소유는 하나여야 한다. 관련만 있는 항목은 `**참조:**` 로 적으세요."
    )


def test_no_adr_entry_names_an_unknown_decision(adr: str) -> None:
    """역방향 — 존재하지 않는 R-D 번호를 적지 않는다. **추적·참조 양쪽 모두**에서."""
    named: set[str] = set()
    for mapping in (_traced_decisions(adr), _referenced_decisions(adr)):
        named |= set().union(*mapping.values()) if mapping else set()
    unknown = sorted(named - ALL_DECISIONS)
    assert not unknown, (
        f"#394 결정 원장에 없는 번호를 적습니다: {', '.join(unknown)} — "
        f"오늘의 원장은 R-D01~R-D{DECISION_COUNT:02d} 다."
    )


def test_every_adr_entry_declares_a_trace_or_a_reference(adr: str) -> None:
    """어느 상위 결정과도 연결되지 않은 항목이 없다.

    소유하면 `**추적:**`, 관련만 있으면 `**참조:**`. 둘 다 없는 항목은 어디서 왔는지 모른다.
    """
    traced, referenced = _traced_decisions(adr), _referenced_decisions(adr)
    dangling = sorted(name for name in _adr_entries(adr) if not traced[name] and not referenced[name])
    assert not dangling, f"`**추적:**` 도 `**참조:**` 도 없는 ADR 항목: {', '.join(dangling)}"


def test_a_reference_never_doubles_as_ownership(adr: str) -> None:
    """참조가 소유를 겸하지 않는다 — 같은 항목이 한 결정을 추적하면서 참조하지 않는다."""
    traced, referenced = _traced_decisions(adr), _referenced_decisions(adr)
    both = {name: sorted(traced[name] & referenced[name]) for name in traced if traced[name] & referenced[name]}
    assert not both, f"같은 항목이 한 결정을 추적이자 참조로 적습니다: {both}"


def test_the_trace_detector_notices_a_dropped_decision(adr: str) -> None:
    """음성 대조 — 추적에서 R-D 하나를 빼면 검출된다."""
    victim = "R-D17"
    tampered = adr.replace(f"**추적:** {victim}", "**추적:** R-D04")
    assert tampered != adr, "합성 대상 추적 줄을 찾지 못했습니다(fixture 회귀)."
    assert victim not in _owners(tampered), "추적 줄에서 결정을 빼도 추출기가 여전히 본다 — 판별력 0."


def test_the_owner_detector_notices_shared_ownership(adr: str) -> None:
    """음성 대조 — 두 항목이 같은 결정을 주장하는 사본에서 검출된다(초판의 실제 형상)."""
    tampered = adr.replace("**참조:** R-D05 (소유는 ADR-03)", "**추적:** R-D05 (소유는 ADR-03)", 1)
    assert tampered != adr, "합성 대상 참조 줄을 찾지 못했습니다(fixture 회귀)."
    assert len(_owners(tampered).get("R-D05", [])) == 2, (
        "참조를 추적으로 바꿔도 소유 중복이 보이지 않는다 — 판별력 0."
    )


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

    **표의 행으로** 있는지를 묻는다. 파일 전체 부분열 검사면 산문에 남은 언급이 표에서 빠진
    항목을 가려 준다 — 등재는 표가 지는 것이고 산문은 등재가 아니다.

    **존재는 단언하지 않는다.** #402·#403 이 아직 착지하지 않은 중간 master 에서 존재를 요구하면
    이 게이트가 R-D12(각 병합 시점 master 의 실행·검증 가능)를 깬다.
    """
    rows = _map_table_rows(readme)
    assert rows, "문서 지도에서 표 행을 하나도 찾지 못했습니다(추출 회귀)."
    registered = "\n".join(row[0] for row in rows)
    missing = [name for name in R1_ARTIFACTS if name not in registered]
    assert not missing, (
        f"문서 지도의 표에 등재되지 않은 R1 산출물: {', '.join(missing)} — 산문 언급은 등재가 아니다."
    )


def test_the_document_map_reflects_the_superseded_status(readme: str) -> None:
    """지도의 웹 재렌더 보존 행이 「부분 대체」다 — 머리말과 지도가 함께 움직인다."""
    row = _map_row(readme, "WEB_RENDER_PRESERVATION.md")
    assert row is not None, "문서 지도에서 웹 재렌더 보존 행을 찾지 못했습니다."
    assert _row_status(row) == "부분 대체", (
        f"지도의 웹 재렌더 보존 행 상태가 '{_row_status(row)}' 입니다 — '부분 대체' 여야 합니다."
    )


def test_every_mapped_document_header_agrees_with_the_map(readme: str) -> None:
    """지도가 부여한 상태와 그 문서 **자신의 머리말**이 같다 — 저장소 전체에서.

    이 단언만 이 파일에서 ADR 범위를 넘는다. 결함류가 넘기 때문이다: 「문서가 스스로에 대해
    주장하는 것과 정본 지도가 말하는 것이 갈린다」는 한 파일의 사고가 아니다. 실제로 이 PR 의
    ADR 자신이 머리말에 `현재 정본`, 지도에 `유효 결정` 을 적어 **두 상태의 편집 원칙이
    정반대**인 채로 착지할 뻔했다(리뷰 지적, PR #456). 한 짝만 검사하던 것을 전 짝으로 넓힌다.

    면제는 **명시 목록**이고, 목록이 실제 불일치 집합과 정확히 같아야 한다 — 새 면제를 조용히
    끼워 넣지도, 고쳐 놓고 목록에 남겨 두지도 못한다. `test_web_source_role.py` 가 쓰는 형식이다.
    """
    mismatched: dict[str, str] = {}
    for rel, map_status in _map_linked_documents(readme).items():
        target = DOCS / rel
        if not target.exists():
            mismatched[rel] = "지도가 가리키는 파일이 없다"
            continue
        declared = _header_field(target.read_text(encoding="utf-8"), "문서 상태")
        if declared is None:
            mismatched[rel] = f"머리말에 문서 상태가 없다 (지도={map_status})"
        elif _status_token(declared) != map_status:
            mismatched[rel] = f"지도={map_status} · 머리말={_status_token(declared)}"

    unexpected = {rel: why for rel, why in mismatched.items() if rel not in HEADER_STATUS_EXEMPTIONS}
    assert not unexpected, (
        "문서 지도와 머리말의 상태가 갈립니다 — 두 상태는 편집 원칙이 다르므로 읽는 사람이 "
        f"모순된 안내를 받습니다:\n{json.dumps(unexpected, ensure_ascii=False, indent=2)}"
    )
    healed = sorted(set(HEADER_STATUS_EXEMPTIONS) - set(mismatched))
    assert not healed, (
        f"면제 목록에 남아 있지만 이미 일치합니다: {healed} — 면제를 지우세요(고친 것이 "
        "면제 목록에 남으면 그 목록이 다음 드리프트를 가립니다)."
    )


def test_the_map_detectors_notice_a_dropped_row(readme: str) -> None:
    """음성 대조 — **표 행만** 지우고 산문 언급은 남긴 사본에서도 검출된다.

    변형을 최소로 한다. 전역 치환으로 음성 대조를 만들면 「표에서 사라졌지만 산문에는 남았다」는
    바로 그 구멍이 대조에서 가려진다 — 음성 대조가 자기가 증명하려던 판별력을 스스로 감춘다.
    """
    row = next(r for r in _map_table_rows(readme) if "react_verification_ledger.toml" in r[0])
    line = next(line for line in readme.splitlines() if line.strip().startswith(f"| {row[0]} |"))
    tampered = readme.replace(f"{line}\n", "") + "\n산문에는 react_verification_ledger.toml 이 남는다.\n"
    assert "react_verification_ledger.toml" in tampered, "합성 사본이 산문 언급을 잃었습니다."
    registered = "\n".join(r[0] for r in _map_table_rows(tampered))
    assert "react_verification_ledger.toml" not in registered, (
        "표 행을 지워도 등재 검사가 통과한다 — 산문이 표를 가리고 있다(판별력 0)."
    )

    reverted = readme.replace(
        "| [웹 재렌더 보존](WEB_RENDER_PRESERVATION.md) | 부분 대체 |",
        "| [웹 재렌더 보존](WEB_RENDER_PRESERVATION.md) | 유효 결정 |",
        1,
    )
    assert _row_status(_map_row(reverted, "WEB_RENDER_PRESERVATION.md")) == "유효 결정", (
        "지도 행 상태를 되돌려도 추출기가 새 값을 본다 — 판별력 0."
    )


# --------------------------------------------------------------------------- #
# 술어 4 — 분류 어휘 5종의 철자
# --------------------------------------------------------------------------- #


def test_adr_defines_the_classification_vocabulary_verbatim(adr: str) -> None:
    """#402 TOML 이 enum 으로 쓸 철자가 ADR 「권위 분류 어휘」 **표에** 정확히 그대로 있다.

    정본은 그 표이므로 그 표를 읽는다. 파일 전체 부분열 검사면 표에서 값이 지워져도 아래
    산문에 그 이름이 한 번 더 나오는 것만으로 초록이 유지된다 — 실제로 이 문서에서
    `p_review_required` 는 표 바로 아래 문단에 다시 등장한다.

    집합 상등으로 본다. 없는 값뿐 아니라 **표에만 몰래 늘어난 값**도 잡아야 #402 enum 이
    정본과 갈리지 않는다.
    """
    declared = _declared_vocabulary(adr)
    assert declared == CLASSIFICATION_VOCABULARY, (
        "ADR 「권위 분류 어휘」 표가 정본 어휘와 다릅니다 — "
        f"빠짐: {sorted(CLASSIFICATION_VOCABULARY - declared)} · "
        f"군더더기: {sorted(declared - CLASSIFICATION_VOCABULARY)}"
    )


def test_the_vocabulary_detector_notices_a_respell_hidden_by_prose(adr: str) -> None:
    """음성 대조 — **표 행만** 고치고 산문은 그대로 둔 사본에서 검출된다.

    변형이 최소여야 판별력이 증명된다. 전역 치환은 「표에서만 사라졌다」는 경우를 만들지
    못해, 정작 겨눠야 할 구멍을 지나친다.
    """
    tampered = adr.replace(
        "| `p_review_required` | Python 제품에 남지만", "| `pReviewRequired` | Python 제품에 남지만", 1
    )
    assert tampered != adr, "합성 대상 표 행을 찾지 못했습니다(fixture 회귀)."
    assert "`p_review_required`" in tampered, "산문 언급이 함께 사라졌습니다 — 최소 변형이 아닙니다."
    assert "p_review_required" not in _declared_vocabulary(tampered), (
        "표 행 철자를 바꿔도 검출되지 않는다 — 산문이 표를 가리고 있다(판별력 0)."
    )


# --------------------------------------------------------------------------- #
# 술어 5 — 「직접 브리지」는 세 개의 다른 집합이다
#
# 두 가지를 **따로** 지킨다. 섞으면 둘 다 잃는다:
#   (a) `73473de` 기준선 수치 — R5 가 delta 를 재려고 동결한 값. HEAD 를 좇으면 안 된다.
#       브리지 표면이 바뀔 때마다 덮어써지면 비교 대상 자체가 사라지고, 그동안 필수 게이트는
#       「기준선을 다시 쓰라」며 붉은 채로 머지를 막는다.
#   (b) HEAD 에서 참이어야 하는 **관계** — 셋이 서로 다른 집합이고, 산문이 유령을 열거하지
#       않는다. 크기는 바뀌어도 되지만 이 관계가 깨지면 ADR 의 주장이 거짓이 된다.
# --------------------------------------------------------------------------- #


def test_adr_records_three_named_bridge_sets(adr: str) -> None:
    """세 집합이 각각 **이름과 크기**로 등장한다 — 단일 수로 적으면 무엇을 센 수인지 잃는다."""
    recorded = _recorded_set_sizes(adr)
    missing = [name for name in SET_NAMES if name not in recorded]
    assert not missing, f"ADR 이 이름과 크기로 적지 않은 직접 브리지 집합: {', '.join(missing)}"


def test_recorded_bridge_set_sizes_stay_frozen_at_the_baseline(adr: str) -> None:
    """ADR 의 세 수가 `73473de` 동결 기준선 그대로다 — **HEAD 를 좇지 않는다**.

    이 수는 R5 가 delta 를 재는 기준선이다. HEAD 재측정에 묶으면 R2 가 브리지 메서드를 하나
    더하는 순간 게이트가 붉어지고, 그것을 풀려면 기준선을 덮어써야 하며, 그 순간 비교 대상이
    사라진다. 그래서 대조 상대는 저장소 HEAD 가 아니라 **동결 상수**다.

    이 단언이 붉어지는 경우는 하나뿐이다: 누가 ADR 의 기준선 표를 고쳤을 때. 그때는 고치지
    말라고 말해 주는 것이 옳다 — 기준선은 갱신 대상이 아니라 보존 대상이다.
    """
    recorded = _recorded_set_sizes(adr)
    drifted = {
        name: (recorded.get(name), BASELINE_BRIDGE_SET_SIZES[name])
        for name in SET_NAMES
        if recorded.get(name) != BASELINE_BRIDGE_SET_SIZES[name]
    }
    assert not drifted, (
        f"ADR 기준선 표가 동결값과 다릅니다 (기재 → 동결): {drifted} — "
        "이 수는 `73473de` 실측이고 R5 delta 의 기준이라 HEAD 에 맞춰 고치는 값이 아닙니다. "
        "오늘의 표면이 궁금하면 아래 관계 단언이 HEAD 에서 봅니다."
    )


def test_the_three_sets_really_are_different_sets_today() -> None:
    """HEAD 에서 셋이 실제로 **서로 다른 집합**이다 — ADR 의 주장이 오늘 참인지를 본다.

    크기가 아니라 원소로 본다. 크기 비교는 우연히 같은 수가 나올 때 침묵하고, 반대로 표면이
    정상적으로 자라기만 해도 시끄럽다. 지켜야 할 것은 「셋이 다르다」이지 「셋이 21·24·23」이
    아니다.
    """
    prose = _prose_bridge_methods(UI_CONTRACT_PATH.read_text(encoding="utf-8"))
    gate = _gate_bridge_methods(BRIDGE_JS_PATH.read_text(encoding="utf-8"))
    python = _python_reachable_methods()

    assert prose and gate and python, (
        f"집합 추출이 비었습니다(추출 회귀): 산문 {len(prose)} · 게이트 {len(gate)} · Python {len(python)}"
    )
    collapsed = [
        f"{left_name} == {right_name}"
        for left_name, left, right_name, right in (
            ("산문 정본 집합", prose, "Python 도달 집합", python),
            ("산문 정본 집합", prose, "게이트 대조 집합", gate),
            ("Python 도달 집합", python, "게이트 대조 집합", gate),
        )
        if left == right
    ]
    assert not collapsed, (
        f"직접 브리지 집합 둘이 같아졌습니다: {', '.join(collapsed)} — "
        "ADR 이 셋을 구분해 적을 이유가 사라졌으므로 ADR 을 갱신하세요."
    )


def test_the_prose_bridge_list_is_complete_in_both_directions() -> None:
    """산문 정본 절이 **제품 직접 브리지 집합과 정확히 같다** — 유령도, 누락도 없다.

    한 방향(유령)만 보면 **누락이 보이지 않는다.** 그리고 누락은 조용하다: 어떤 이름을 정본
    절에서 지워도 그 이름이 문서 다른 곳에 남아 있으면 오늘의 두 게이트가 **둘 다 초록**이다.
    이쪽은 절만 보고 유령만 찾았고, `test_architecture.py:399` 는 파일 전체에서 backtick 을
    찾는다. 실물이 있다 — `generate` 는 `docs/UI_CONTRACT.md:36`(정본 절)과 `:463`(다른 절)
    두 곳에 있어, 정본 절에서 지워도 아무도 붉어지지 않는다(리뷰 지적, PR #456).

    비교 상대는 **유도한다** — 이름을 손으로 적으면 그 목록이 다음 드리프트의 자리가 된다.
    제품 직접 브리지 = `bridge.js` 의 `api.<이름>` ∩ `WebFrontend` 공개 표면. 교집합이
    selftest 소유 메서드(`selftest_claim`·`selftest_host_op`)를 자동으로 떨군다 —
    그것들은 `WebFrontend` 메서드가 아니기 때문이다.
    """
    prose = _prose_bridge_methods(UI_CONTRACT_PATH.read_text(encoding="utf-8"))
    gate = _gate_bridge_methods(BRIDGE_JS_PATH.read_text(encoding="utf-8"))
    product_direct = gate & _python_reachable_methods()

    assert prose and product_direct, (
        f"집합 추출이 비었습니다(추출 회귀): 산문 {len(prose)} · 제품 직접 브리지 {len(product_direct)}"
    )
    ghosts = sorted(prose - product_direct)
    omissions = sorted(product_direct - prose)
    assert not ghosts and not omissions, (
        "UI 계약 「직접 브리지 경로」 절이 제품 직접 브리지 집합과 다릅니다 — "
        f"유령(절에는 있으나 실재 없음): {ghosts} · "
        f"누락(브리지가 부르는데 절에 없음): {omissions}"
    )


def test_the_baseline_detector_notices_an_overwritten_number(adr: str) -> None:
    """음성 대조 — 기준선 표 행 하나를 덮어쓴 사본에서 검출된다."""
    victim = "게이트 대조 집합"
    frozen = BASELINE_BRIDGE_SET_SIZES[victim]
    tampered = adr.replace(f"| **{victim}** | {frozen} |", f"| **{victim}** | {frozen + 1} |", 1)
    assert tampered != adr, "합성 대상 표 행을 찾지 못했습니다(fixture 회귀)."
    assert _recorded_set_sizes(tampered)[victim] != frozen, (
        "기준선 수를 덮어써도 검출되지 않는다 — 판별력 0."
    )


def test_the_collapse_detector_notices_two_sets_becoming_one() -> None:
    """음성 대조 — 두 집합이 같아진 합성 트리에서 검출된다.

    실재 유령이 없는 축이라 합성으로 세운다(오늘 셋은 서로 다르다). 산문 절이 게이트 집합과
    똑같은 목록을 열거하도록 조작한 사본을 만들어, 그 붕괴가 실제로 보이는지 확인한다.
    """
    gate = _gate_bridge_methods(BRIDGE_JS_PATH.read_text(encoding="utf-8"))
    synthetic_contract = (
        "- **직접 브리지 경로:** " + ", ".join(f"`{name}`" for name in sorted(gate)) + "\n\n### 끝\n"
    )
    assert _prose_bridge_methods(synthetic_contract) == gate, (
        "합성 사본에서 산문 집합이 게이트 집합과 같아지지 않았다 — 붕괴를 만들지 못하면 "
        "그 축의 판별력을 증명할 수 없다."
    )
