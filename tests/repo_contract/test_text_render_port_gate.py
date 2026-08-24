"""S10-04(#861) static guard: TXT 치환·카드 렌더의 직결 소비자를 명시 열거로 봉인한다.

slot-bearing TXT 의 산출물은 이제 **Sealed Plan 이 정한 물질화**를 지난다(구간 제거 → 마커
소거 → 치환 → 후행조건 재검증). 그 경로를 우회해 ``render_segments``/``render_record`` 를 직접
부르면, 고르지 않은 선택지와 마커 텍스트가 그대로 실린 텍스트가 나가는 옛 결함이 되살아난다.

그래서 「누가 치환을 직접 부를 수 있는가」를 이 계약이 못박는다. 열거된 자리는 전부 **구간
표기와 무관한 축**이거나(토큰 미리보기·원문 보기·slotless 복사) **물질화 코어 자신**이다:

- 정의 모듈과 그 링1 래퍼(:mod:`hwpxfiller.gui.txt_card`)
- TXT materializer — 치환의 단일 원천을 소비하는 정당한 주체
- 작업대(:mod:`hwpxfiller.webapp.screen_workbench`) — 원문 보기와 slotless 카드
- 편집기(:mod:`hwpxfiller.webapp.screen_editor`) — 토큰 **미리보기**(빈 레코드), 문서를
  만들지 않는다
- CLI(:mod:`hwpxfiller.cli`) — slotless 전용(구간 표기가 있으면 시끄럽게 거절한다)

``template_fields`` 는 감싸지 않는다: 그것은 「이 템플릿이 참조하는 이름이 무엇인가」를 묻는
읽기 술어라 문서를 만들지 않고, 소비자가 넓다(화면 공용·TXT 레지스트리·맞추기 표). 감싸는
것은 **값을 꽂거나 카드 문자열을 만드는** 함수뿐이다.

스캐너 자체는 음성 대조로 검증한다(#805 교훈 — 사본이 아니라 실 스캐너를 태운다).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

#: 감쌀 대상 — 「토큰을 값으로 바꾸는」·「카드 문자열을 만드는」 함수들.
GUARDED_SYMBOLS = frozenset(
    {
        "render_segments",
        "render_record",
        "render_card",
        "card_text",
        "align_segments",
    }
)

#: 소유자 열거(실측 확정). 목록 밖의 새 직결 소비자는 RED 다 — 필요하면 계약 변경으로 넓힌다.
ALLOWED_MODULES = frozenset(
    {
        # 정의와 링1 래퍼
        "src/hwpxfiller/domain/text_render.py",
        "src/hwpxfiller/gui/txt_card.py",
        # 물질화 코어 — 치환의 단일 원천을 소비하는 정당한 주체
        "src/hwpxfiller/external/text_materialization_conformance.py",
        # 표시 표면(원문 보기·카드·토큰 미리보기)
        "src/hwpxfiller/webapp/screen_workbench.py",
        "src/hwpxfiller/webapp/screen_editor.py",
        # slotless 전용 CLI
        "src/hwpxfiller/cli.py",
    }
)


def _guarded_uses(source: str, label: str) -> list[str]:
    """모듈이 guarded 심볼을 이름·속성·import·정의 어디서든 만지면 그 자리를 센다.

    정의(:class:`ast.FunctionDef`)까지 세는 이유는 port gate 와 같다: 소유자 밖 모듈이 같은
    이름을 재정의하는 그림자 경로도 두 번째 치환기다.
    """
    sites: list[str] = []
    tree = ast.parse(source, filename=label)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in GUARDED_SYMBOLS:
            sites.append(f"{label}:{node.lineno}:{node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in GUARDED_SYMBOLS:
            sites.append(f"{label}:{node.lineno}:{node.attr}")
        elif isinstance(node, ast.FunctionDef) and node.name in GUARDED_SYMBOLS:
            sites.append(f"{label}:{node.lineno}:{node.name}")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in GUARDED_SYMBOLS:
                    sites.append(f"{label}:{node.lineno}:{alias.name}")
    return sites


def test_direct_text_substitution_has_an_enumerated_owner_set() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        label = str(path.relative_to(ROOT)).replace("\\", "/")
        if label in ALLOWED_MODULES:
            continue
        offenders += _guarded_uses(path.read_text(encoding="utf-8"), label)
    assert not offenders, (
        "TXT 치환·카드 렌더를 열거 밖 production 코드가 직접 만진다 — 물질화(구간 제거·마커 "
        "소거·후행조건)를 우회하는 두 번째 산출 경로 금지(S10-04 #861):\n"
        + "\n".join(offenders)
    )


def test_owner_modules_actually_use_the_symbols() -> None:
    """열거가 화석이 되지 않게: 소유자는 guarded 심볼을 실제로 정의/소비하고 있어야 한다."""
    for label in sorted(ALLOWED_MODULES):
        source = (ROOT / label).read_text(encoding="utf-8")
        assert _guarded_uses(source, label), f"{label} 이 guarded 심볼을 더는 쓰지 않는다"


def test_cli_render_refuses_structure_notation_before_substituting() -> None:
    """CLI 의 직결 치환이 **구간 표기 검문 뒤에만** 도달함을 소스 순서로 못박는다.

    열거만으로는 「CLI 가 slotless 전용이다」가 증명되지 않는다 — 그 자격은 거절 검문이
    치환보다 먼저 서는 데서 온다. 검문이 사라지거나 뒤로 밀리면 여기서 빨강이다.
    """
    source = (ROOT / "src/hwpxfiller/cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="cli.py")
    render_main = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_render_main"
    )
    scan_lines = [
        node.lineno
        for node in ast.walk(render_main)
        if isinstance(node, ast.Name) and node.id == "scan_text_structure"
    ]
    call_lines = [
        node.lineno
        for node in ast.walk(render_main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "render_record"
    ]
    assert scan_lines and call_lines, (scan_lines, call_lines)
    assert max(scan_lines) < min(call_lines), (
        "CLI render 가 구간 표기 검문보다 먼저 치환한다 — 고르지 않은 선택지와 마커가 실린 "
        "텍스트가 그대로 나간다"
    )


def test_negative_probe_detects_direct_substitution() -> None:
    # 음성 대조는 실 스캐너를 태운다(#805) — import·호출·attribute·그림자 정의 모두 잡는다.
    assert _guarded_uses(
        "from hwpxfiller.domain.text_render import render_record\n", "probe.py"
    ) == ["probe.py:1:render_record"]
    assert _guarded_uses("text, report = render_record(t, r)\n", "probe.py") == [
        "probe.py:1:render_record"
    ]
    assert _guarded_uses("text_render.render_segments(t, {})\n", "probe.py") == [
        "probe.py:1:render_segments"
    ]
    assert _guarded_uses("def card_text(segments):\n    return ''\n", "probe.py") == [
        "probe.py:1:card_text"
    ]
    assert _guarded_uses("x = 1\n", "probe.py") == []
