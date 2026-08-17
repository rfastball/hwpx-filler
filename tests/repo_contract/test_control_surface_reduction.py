"""SG-03(#735) control-surface reduction 정적 게이트 — C1·C2·C3·C4·C6.

v1 제품 표면은 이미 **구성상** 축소돼 있다(census: `docs/CONTROL_PLANE_SCOPE.md`). 이 파일은
그 사실들을 pin 해, 미래 변경이 조용히 표면을 재확장하지 못하게 한다. 순수 static 이라 무표
contract lane 에 산다(실 런타임·브라우저 불요). frontend import-graph 는 `tests/_web_source.py`
의 단일 스캐너(`_frontend_sources`·`_frontend_specifiers`·`_resolve_frontend_module`)를 쓴다 —
`test_p3_forbidden_edges` 의 vendor 게이트와 같은 진실이다.

- C1 shipping Qualification Profile count == 1 (+ bootstrap admission 1 · dynamic publication 0).
- C2 제품 Profile selector/management UI == 0.
- C3 production frontend 의 canonical semantic module import == 0.
- C4 production frontend 의 canonical digest 계산·재저작 == 0.
- C6 신규 durable first-seen ledger 가 allowlist 밖에 생기면 RED (baseline 4 pin).

C5 는 `test_bridge_contract.py`(생성 계약 parity), C7/C8 은 `test_slot_configuration_product.py`,
C9 는 `test_control_plane_evidence.py` 가 진다.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from _web_source import (
    NAV_SCREENS,
    _frontend_sources,
    _frontend_specifiers,
    _js_masks,
    _resolve_frontend_module,
)

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src"
FRONTEND_DOMAIN_PREFIX = "frontend/src/domain/"

#: 두 canonical semantic 모듈 — production frontend 이 **import 하지 않아야** 한다.
#: (제품 소비자 0 = census. test/codec 소비는 `tests/js/*` 이라 frontend 스캔 밖이다.)
CANONICAL_SEMANTIC_MODULES = (
    "frontend/src/domain/canonical_execution_encoding.ts",
    "frontend/src/domain/slot_selection.ts",
)

#: canonical semantic 을 재저작했다는 표식이 될 심볼·primitive. production frontend 이
#: 이 이름들을 **정의하거나 참조하면** 두 번째 판정자가 생긴 것이다.
CANONICAL_SEMANTIC_SYMBOLS = (
    "canonicalExecutionBytes",
    "canonicalExecutionDigest",
    "canonicalizeSelectionSet",
    "digestSelectionSet",
    "semanticSelectionEqual",
    "validateSelectionSet",
    "declaredSelectionDigest",
)

#: C6 baseline — 기존 S4/S5 durable first-seen ledger 정확히 4개(census §a). 형식:
#: ``<module 파일명>|<field 이름>|<element type>``. **여기에 손으로 5번째를 더하지 않는다.**
#: 새 ledger 를 실제로 정당화하려면 `docs/CONTROL_PLANE_SCOPE.md` §신규 ledger allowlist 의
#: 외부효과/중복결과 경계에 해당함을 이슈에서 증명하고, allowlist·baseline 을 함께 넓힌다.
LEDGER_BASELINE = frozenset(
    {
        "stored_execution_plan.py|first_seen_ledger|FirstSeenSealCommandRecord",
        "stored_field_binding.py|first_seen_command_ledger|FieldBindingIdempotencyRecord",
        "stored_profile_admission.py|processed_requests|AdmissionIdempotencyRecord",
        "stored_work_configuration.py|processed_requests|IdempotencyRecord",
    }
)

#: 신규 durable ledger 가 허용될 후보 경계(issue §4). allowlist 밖 command 에 ledger 를 더하면
#: 이 메시지로 RED 되고, 상향 여부는 #732/#620 에서 판단한다.
_LEDGER_ALLOWLIST_MESSAGE = (
    "신규 durable first-seen ledger 는 외부효과/중복결과가 입증된 경계에만 허용된다"
    "(StartMaterialization · Artifact publication · filesystem delivery · "
    "overwrite/collision disposition · failed-item retry). baseline 밖 ledger 를 발견했다 — "
    "일반 UI state·Work-local draft·단순 projection command 라면 제거하고, 실제 재전송 중복효과가 "
    "있다면 #732/#620 으로 상향해 allowlist 와 LEDGER_BASELINE 을 함께 넓힌다."
)

_LEDGER_RECORD_SUFFIXES = ("IdempotencyRecord", "SealCommandRecord")


def _short_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _src_files() -> list[Path]:
    return sorted(
        p for p in (SRC / "hwpxfiller").rglob("*.py") if "__pycache__" not in p.parts
    )


def _call_counts() -> Counter[str]:
    """src 전역의 call-target short name 빈도. 정의(def/class)는 세지 않는다."""
    counts: Counter[str] = Counter()
    for path in _src_files():
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _short_name(node.func)
                if name:
                    counts[name] += 1
    return counts


def _profile_constructions() -> list[str]:
    """``QualificationProfile(...)`` 생성 지점을 ``<module>|<assigned-name>`` 으로 돌려준다."""
    found: list[str] = []
    for path in _src_files():
        relative = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if _short_name(node.value.func) == "QualificationProfile":
                    targets = [
                        t.id for t in node.targets if isinstance(t, ast.Name)
                    ]
                    found.append(f"{relative}|{','.join(targets)}")
    return found


def _tuple_element_name(annotation: ast.expr) -> str | None:
    """``tuple[X, ...]`` 주석에서 element type X 의 short name 을 뽑는다(아니면 None)."""
    if not (isinstance(annotation, ast.Subscript) and _short_name(annotation.value) == "tuple"):
        return None
    slice_node = annotation.slice
    if isinstance(slice_node, ast.Tuple) and slice_node.elts:
        return _short_name(slice_node.elts[0])
    return None


def _durable_ledger_fields() -> set[str]:
    """application 전역의 durable first-seen ledger tuple field 를 census 한다.

    frozen aggregate 의 class-body ``AnnAssign`` 중 annotation 이 ``tuple[X, ...]`` 이고 X 가
    ``*IdempotencyRecord``/``*SealCommandRecord`` 로 끝나는 것 — 즉 append-only 멱등 원장.
    """
    found: set[str] = set()
    application = SRC / "hwpxfiller" / "application"
    for path in sorted(application.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for stmt in cls.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                element = _tuple_element_name(stmt.annotation)
                if element and element.endswith(_LEDGER_RECORD_SUFFIXES):
                    found.add(f"{path.name}|{stmt.target.id}|{element}")
    return found


def _canonical_semantic_importers(sources: dict[str, str]) -> set[str]:
    """canonical semantic 모듈로 resolve 되는 frontend import 를 ``<file>|<specifier>`` 로 돌려준다.

    canonical 모듈 자신은 건너뛴다(자기 참조·상호 참조는 도메인 내부다).
    """
    violations: set[str] = set()
    for relative, source in sources.items():
        if relative in CANONICAL_SEMANTIC_MODULES:
            continue
        for specifier in _frontend_specifiers(relative, source):
            target = _resolve_frontend_module(relative, specifier, sources)
            if target in CANONICAL_SEMANTIC_MODULES:
                violations.add(f"{relative}|{specifier}")
    return violations


def _non_domain_frontend_code() -> dict[str, str]:
    """domain canonical 파일을 뺀 production frontend 소스의 **code mask**(문자열/주석 제거)."""
    return {
        relative: _js_masks(source)[1]
        for relative, source in _frontend_sources().items()
        if not relative.startswith(FRONTEND_DOMAIN_PREFIX)
    }


# ─── C1 ──────────────────────────────────────────────────────────────────────────
def test_exactly_one_shipping_qualification_profile() -> None:
    constructions = _profile_constructions()
    assert constructions == [
        "hwpxfiller/external/template_inspection.py|HWPX_QUALIFICATION_PROFILE"
    ], f"shipping Profile 은 정확히 하나여야 한다: {constructions}"

    counts = _call_counts()
    # bootstrap explicit admission 1 (template_change) · dynamic publication route 0 · revoke 0.
    assert counts["initialize_qualification_profile_admission"] == 1, (
        "built-in Profile bootstrap admission 은 production 에서 정확히 1회여야 한다"
    )
    assert counts["register_published_qualification_profile_admission"] == 0, (
        "dynamic Profile publication 은 v1 제품 route 가 없어야 한다(internal/incident/test 전용)"
    )
    assert counts["revoke_qualification_profile"] == 0, (
        "Profile revoke 는 v1 사용자/관리자 제품 표면이 아니다(internal/incident/test 전용)"
    )


# ─── C2 ──────────────────────────────────────────────────────────────────────────
def test_no_profile_management_surface() -> None:
    offenders = sorted(
        relative
        for relative, source in _frontend_sources().items()
        if not relative.startswith(FRONTEND_DOMAIN_PREFIX) and "profile" in source.lower()
    )
    assert not offenders, (
        f"제품 frontend 에 Profile 표면이 생겼다: {offenders} — Profile selector/management UI 는 "
        "v1 에서 0 이다. 복수 runtime/plugin/admin 요구는 별도 설계로 상향한다."
    )
    assert "profile" not in {screen.lower() for screen in NAV_SCREENS}, (
        f"NAV_SCREENS 에 profile route 가 생겼다: {NAV_SCREENS}"
    )


# ─── C3 ──────────────────────────────────────────────────────────────────────────
def test_frontend_does_not_import_canonical_semantics() -> None:
    violations = _canonical_semantic_importers(_frontend_sources())
    assert not violations, (
        f"production frontend 이 canonical semantic 모듈을 import 한다: {sorted(violations)} — "
        "canonical bytes/digest 는 backend/application 단일 권위다. offline/보안상 독립 digest 가 "
        "실제로 필요하면 #732/#620 으로 상향한다."
    )


# ─── C4 ──────────────────────────────────────────────────────────────────────────
def test_frontend_recomputes_no_semantics() -> None:
    code = _non_domain_frontend_code()
    crypto = sorted(rel for rel, masked in code.items() if "crypto.subtle" in masked)
    assert not crypto, (
        f"production frontend 이 digest primitive 를 직접 쓴다: {crypto} — currentness/Plan/record "
        "digest 는 backend 판정이다."
    )
    reauthored = sorted(
        f"{rel}|{symbol}"
        for rel, masked in code.items()
        for symbol in CANONICAL_SEMANTIC_SYMBOLS
        if symbol in masked
    )
    assert not reauthored, (
        f"production frontend 이 canonical semantic 심볼을 참조/재저작한다: {reauthored} — "
        "frontend 는 projection/observation DTO 를 렌더할 뿐 Plan/currentness/record/delivery 를 "
        "재계산하지 않는다."
    )


# ─── C6 ──────────────────────────────────────────────────────────────────────────
def test_no_new_durable_ledger_outside_allowlist() -> None:
    discovered = _durable_ledger_fields()
    new_ledgers = discovered - LEDGER_BASELINE
    assert not new_ledgers, f"{sorted(new_ledgers)} — {_LEDGER_ALLOWLIST_MESSAGE}"
    removed = LEDGER_BASELINE - discovered
    assert not removed, (
        f"기존 S4/S5 durable ledger 가 사라졌다: {sorted(removed)} — SG-03 은 제거·migration 이 "
        "아니라 pin 이다. baseline 을 줄이려면 실제 소비자 부재 증거와 함께 별도 슬라이스로 한다."
    )


# ─── negative probes (파일 관례: 게이트가 위반을 실제로 잡는지) ────────────────────────
def test_negative_probe_detects_extra_shipping_profile() -> None:
    # 두 번째 QualificationProfile 생성이 있으면 census 가 둘을 돌려준다.
    source = (
        "x = QualificationProfile('a', f)\n"
        "y = other.QualificationProfile('b', g)\n"
        "class QualificationProfile: pass\n"  # 정의는 세지 않는다
    )
    tree = ast.parse(source)
    calls = [
        _short_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    assert calls.count("QualificationProfile") == 2


def test_negative_probe_detects_canonical_semantic_import() -> None:
    sources = {
        "frontend/src/domain/canonical_execution_encoding.ts": "export const x = 1;\n",
        "frontend/src/domain/slot_selection.ts": "export const y = 1;\n",
        "frontend/src/screens/probe.ts": (
            'import { canonicalExecutionDigest } from "../domain/canonical_execution_encoding.ts";\n'
        ),
        "frontend/src/screens/dynamic_probe.ts": (
            'const m = await import("../domain/slot_selection.ts");\n'
        ),
    }
    assert _canonical_semantic_importers(sources) == {
        "frontend/src/screens/probe.ts|../domain/canonical_execution_encoding.ts",
        "frontend/src/screens/dynamic_probe.ts|../domain/slot_selection.ts",
    }


def test_negative_probe_detects_new_ledger() -> None:
    # baseline 밖 element type 이면 발견 집합이 baseline 을 초과한다.
    source = (
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True)\n"
        "class NewAggregate:\n"
        "    start_materialization_ledger: tuple[StartMaterializationIdempotencyRecord, ...]\n"
        "    unrelated: tuple[SomeValue, ...]\n"  # Record suffix 아님 → 무시
    )
    tree = ast.parse(source)
    fields: set[str] = set()
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef):
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    element = _tuple_element_name(stmt.annotation)
                    if element and element.endswith(_LEDGER_RECORD_SUFFIXES):
                        fields.add(f"probe.py|{stmt.target.id}|{element}")
    assert fields == {
        "probe.py|start_materialization_ledger|StartMaterializationIdempotencyRecord"
    }
