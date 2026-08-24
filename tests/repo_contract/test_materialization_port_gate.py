"""S6-01(#809) static guard: executor/verifier 의 production 소유자는 materialization runner 하나다.

SG-02 의 executor(:func:`apply_execution_plan_in_memory`)·verifier
(:func:`verify_materialization_postconditions`)·P7 precheck 를 임의 production 모듈이 직접 부르면
fence·조달 digest 대조·postcondition 자격(S6-3) 밖에서 두 번째 materialization 경로가 생긴다 —
링2 의 판정 재조립 금지(S6-10)와 같은 원칙의 정적 얼굴이다. 소유자 집합을 명시 열거하고,
스캐너 자체는 음성 대조로 검증한다(#805 교훈).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# 감쌀 대상 함수 — 이 이름을 import 하거나 attribute 로 만지는 production 모듈은 소유자여야 한다.
GUARDED_SYMBOLS = frozenset(
    {
        "apply_execution_plan_in_memory",
        "verify_structure_bytes_consistency",
        "verify_materialization_postconditions",
        # TXT 축(S10-04 · #861) — 같은 계약, 다른 매체. 러너 밖에서 부르면 조달 digest 대조와
        # 단계별 postcondition 밖의 두 번째 물질화 경로가 생기는 것도 똑같다.
        "apply_txt_execution_plan_in_memory",
        "verify_txt_structure_bytes_consistency",
        "verify_txt_materialization_postconditions",
    }
)

# 소유자: 정의 모듈 + 유일 production 소비자(러너). S6-02/04 는 러너를 감싸지, 이 함수들을
# 직접 부르지 않는다 — 새 소유자가 필요하면 이 열거를 계약 변경으로 넓힌다.
ALLOWED_MODULES = frozenset(
    {
        "src/hwpxfiller/external/materialization_conformance.py",
        "src/hwpxfiller/external/materialization_runner.py",
        "src/hwpxfiller/external/text_materialization_conformance.py",
        "src/hwpxfiller/external/text_materialization_runner.py",
    }
)


def _guarded_uses(source: str, label: str) -> list[str]:
    """모듈이 guarded 심볼을 이름·속성·import·정의 어디서든 만지면 그 자리를 센다.

    정의(:class:`ast.FunctionDef`)까지 세는 이유: 소유자 밖 모듈이 같은 이름을 재정의하는
    그림자 경로도 두 번째 materializer 다.
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


def test_executor_verifier_have_single_production_owner() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        label = str(path.relative_to(ROOT)).replace("\\", "/")
        if label in ALLOWED_MODULES:
            continue
        offenders += _guarded_uses(path.read_text(encoding="utf-8"), label)
    assert not offenders, (
        "materialization executor/verifier 를 러너 밖 production 코드가 직접 만진다 — "
        "fence·digest 조달·postcondition 자격 밖의 두 번째 materialization 경로 금지(S6-10):\n"
        + "\n".join(offenders)
    )


def test_owner_modules_actually_use_the_symbols() -> None:
    # 열거가 화석이 되지 않게: 소유자 두 모듈은 guarded 심볼을 실제로 정의/소비하고 있어야 한다.
    for label in sorted(ALLOWED_MODULES):
        source = (ROOT / label).read_text(encoding="utf-8")
        assert _guarded_uses(source, label), f"{label} 이 guarded 심볼을 더는 쓰지 않는다"


def test_negative_probe_detects_direct_executor_call() -> None:
    # 음성 대조는 실 스캐너를 태운다(#805) — import·호출·attribute 세 형태 모두 잡는다.
    assert _guarded_uses(
        "from hwpxfiller.external.materialization_conformance import apply_execution_plan_in_memory\n",
        "probe.py",
    ) == ["probe.py:1:apply_execution_plan_in_memory"]
    assert _guarded_uses(
        "result = verify_materialization_postconditions(source_bytes=b'', output_bytes=b'')\n",
        "probe.py",
    ) == ["probe.py:1:verify_materialization_postconditions"]
    assert _guarded_uses(
        "conformance.verify_structure_bytes_consistency(candidate_bytes=b'', structure=s)\n",
        "probe.py",
    ) == ["probe.py:1:verify_structure_bytes_consistency"]
    assert _guarded_uses(
        "def apply_execution_plan_in_memory(**kw):\n    pass\n", "probe.py"
    ) == ["probe.py:1:apply_execution_plan_in_memory"]
    assert _guarded_uses("x = 1\n", "probe.py") == []
