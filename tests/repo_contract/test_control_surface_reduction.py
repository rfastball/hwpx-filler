"""SG-03(#735) control-surface reduction 정적 게이트 — C1·C2·C3·C4·C6.

v1 제품 표면은 이미 **구성상** 축소돼 있다(census: `docs/CONTROL_PLANE_SCOPE.md`). 이 파일은
그 사실들을 pin 해, 미래 변경이 조용히 표면을 재확장하지 못하게 한다. 순수 static 이라 무표
contract lane 에 산다(실 런타임·브라우저 불요). frontend import-graph 는 `tests/_web_source.py`
의 단일 스캐너(`_frontend_sources`·`_frontend_specifiers`·`_resolve_frontend_module`)를 쓴다 —
`test_p3_forbidden_edges` 의 vendor 게이트와 같은 진실이다.

각 negative probe 는 **실제 게이트 함수 자체**를 정확한 회피 표본에 대고 호출해 RED 됨을 보인다
(병렬 재구현이 아니다). 회피표본에서 RED 를 못 내는 게이트는 무가치이고, 이 슬라이스의 산출물이
곧 이 게이트들이라 hollow gate 는 결함이다.

- C1 shipping Qualification Profile count == 1 (+ bootstrap admission 1 · dynamic publication 0 · revoke 0).
- C2 제품 Profile/qualification 관리 표면(action·bridge·screen) == 0.
- C3 production frontend 의 `frontend/src/domain/` semantic module import == 0.
- C4 production frontend 의 canonical digest 계산·재저작 == 0(retained codec 2개만 제외).
- C6 durable aggregate 의 append-only record 필드가 pinned manifest 밖으로 늘면 RED.

C5 는 `test_bridge_contract.py`(생성 계약 parity), C7/C8 은 `test_slot_configuration_product.py`,
C9 는 `test_control_plane_evidence.py` 가 진다.
"""

from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from _web_source import (
    NAV_SCREENS,
    _frontend_sources,
    _frontend_specifiers,
    _js_masks,
    _resolve_frontend_module,
)

from hwpxfiller.webapp.action_registry import ACTION_REGISTRY
from hwpxfiller.webapp.app import WebFrontend

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src"
FRONTEND_DOMAIN_PREFIX = "frontend/src/domain/"

#: 유지되는 wire codec 모듈 **정확히 둘** — 이것들만 semantic-scan/​import-ban 에서 예외다.
#: (제품 소비자 0 = census; test/codec 소비는 `tests/js/*` 이라 frontend 스캔 밖이다.)
#: 디렉터리 전체를 예외로 두지 않는다: `frontend/src/domain/` 에 새 파일(예: currentness.ts)이
#: 생기면 그것은 C3(import 금지)·C4(재계산 스캔) 양쪽의 **대상**이다.
RETAINED_CODEC_MODULES = (
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

#: profile/qualification 관리 표면을 겨누는 금지어. 영어 substring 이 아니라 **구조적 표면**
#: (action registry·direct-bridge method·screen/route 상수)의 이름을 census 해 이 토큰을 본다 —
#: 지역화된 라벨(`qualificationPolicy`)이 raw 소스 substring 을 빠져나가는 hollow 를 막는다.
_PROFILE_SURFACE_TERMS = ("profile", "qualification")

#: durable aggregate 모듈 — 여기 있는 frozen dataclass 의 append-only record 필드만 census 한다.
#: (application 전역을 훑지 않는다: in-memory DTO 를 과포획한다.)
DURABLE_AGGREGATE_MODULES = (
    "stored_execution_plan.py",
    "stored_field_binding.py",
    "stored_work_configuration.py",
    "work_slot_configuration.py",
)

#: C6 baseline — durable aggregate 의 **모든** append-only record 필드(naming-independent census).
#: 형식: ``<module 파일명>|<field 이름>|<element type>``. record 이름 suffix 가 아니라 **형상**
#: (frozen dataclass 를 담은 tuple/Sequence 필드)으로 census 하므로, `IdempotencyRecord`/
#: `SealCommandRecord` 규약을 안 따르는 record(예: `ProcessedCommand`)도 잡힌다. 처음 4개(멱등
#: 원장)보다 넓은 것은 census 를 이름-독립으로 돌린 실제 집합이다 — first-seen 멱등 원장 4개에
#: 더해 revision/draft/decision/config 같은 durable append-only 사본 필드가 함께 pin 된다.
#: **여기에 손으로 항목을 더하지 않는다.** 새 durable record 필드를 정당화하려면
#: `docs/CONTROL_PLANE_SCOPE.md` §신규 ledger allowlist 의 외부효과/중복결과 경계에 해당함을
#: 이슈에서 증명하고, allowlist·baseline 을 함께 넓힌다.
LEDGER_BASELINE = frozenset(
    {
        # S5F R2-04a(#740): stored_execution_plan 의 first-seen seal request ledger 를 제거했다 —
        # seal 은 historical outcome 을 replay 하지 않고 현재 authority 에서 재계산한다(idempotency/
        # replay 소비자 부재). content-addressed Plan history 는 04b 대상으로 남는다.
        "stored_field_binding.py|current_by_application|ApplicationRevisionPointer",
        "stored_field_binding.py|immutable_binding_revisions|FieldBindingRevision",
        "stored_field_binding.py|migration_drafts|CommittedDraftRecord",
        "stored_field_binding.py|application_review_drafts|CommittedDraftRecord",
        "stored_field_binding.py|first_seen_command_ledger|FieldBindingIdempotencyRecord",
        "stored_work_configuration.py|processed_requests|IdempotencyRecord",
        "work_slot_configuration.py|configurations|WorkSlotConfigurationDraft",
    }
)

#: 신규 durable record 필드가 허용될 후보 경계(issue §4). allowlist 밖 필드를 더하면 이 메시지로
#: RED 되고, 상향 여부는 #732/#620 에서 판단한다.
_LEDGER_ALLOWLIST_MESSAGE = (
    "신규 durable append-only record 필드는 외부효과/중복결과가 입증된 경계에만 허용된다"
    "(StartMaterialization · Artifact publication · filesystem delivery · "
    "overwrite/collision disposition · failed-item retry). baseline 밖 durable record 필드를 "
    "발견했다 — 일반 UI state·Work-local draft·단순 projection command 라면 제거하고, 실제 재전송 "
    "중복효과가 있다면 #732/#620 으로 상향해 allowlist 와 LEDGER_BASELINE 을 함께 넓힌다."
)


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


# ─── C1 helpers: 생성 census + alias-resolving 호출 census ──────────────────────────
def _import_alias_map(tree: ast.Module) -> dict[str, str]:
    """``from … import orig as alias`` 의 ``{alias: orig}`` 을 만든다.

    alias 로 부른 호출이 원래 이름으로 세지도록 한다 — ``revoke_qualification_profile as
    revoke_profile`` 로 숨겨도 census 가 원 이름으로 잡는다.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for name in node.names:
                if name.asname:
                    aliases[name.asname] = name.name
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.asname:
                    aliases[name.asname] = name.name.split(".")[-1]
    return aliases


# R2-05a(#740)로 제거된 mutable Profile admission 제어면의 호출 이름 — C1 census 와 그 음성 대조가
# **같은 이 목록**을 소비한다(S6G-00 #806 · #805). 프로브가 겨누는 표면이 census 가 세는 표면과
# 다르면 프로브는 아무 위반도 잡지 못하므로, 두 자리가 문자열을 각자 들고 있지 않게 한다.
REMOVED_ADMISSION_CONTROL_CALLS = (
    "initialize_qualification_profile_admission",
    "register_published_qualification_profile_admission",
    "revoke_qualification_profile",
)

# 음성 대조가 fabricate 하는 import 의 출처 — **실재하는** 모듈이어야 한다. 삭제된 모듈을 쓰면
# 읽는 사람이 그 표면을 현재로 오해하고, 프로브가 무엇을 지키는지도 흐려진다.
_LIVE_IMPORT_SOURCE_MODULE = "hwpxfiller.external.qualification_store"


def _call_counts_in(source: str, filename: str = "<probe>") -> Counter[str]:
    """한 소스의 call-target short name 빈도(import alias 를 원 이름으로 해소). 정의는 안 센다."""
    tree = ast.parse(source, filename=filename)
    aliases = _import_alias_map(tree)
    counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _short_name(node.func)
            if name:
                counts[aliases.get(name, name)] += 1
    return counts


def _call_counts() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in _src_files():
        counts += _call_counts_in(path.read_text(encoding="utf-8"), filename=str(path))
    return counts


def _profile_constructions_in(relative: str, source: str) -> list[str]:
    """한 소스의 **모든** ``QualificationProfile(...)`` 생성 지점을 ``<module>|<label>`` 로 돌려준다.

    ``ast.Assign`` 뿐 아니라 annotated assignment(``x: T = QualificationProfile(...)``),
    return, call-arg 등 **어떤 배치**의 생성도 센다(호출 노드 자체를 겨눈다). label 은 대입/주석
    대상 이름이거나, 그 밖의 문맥이면 ``<inline>`` 이다.
    """
    tree = ast.parse(source, filename=relative)
    labels: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets:
                labels[id(node.value)] = ",".join(targets)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.target, ast.Name)
        ):
            labels[id(node.value)] = node.target.id
    return [
        f"{relative}|{labels.get(id(node), '<inline>')}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _short_name(node.func) == "QualificationProfile"
    ]


def _profile_constructions() -> list[str]:
    found: list[str] = []
    for path in _src_files():
        relative = path.relative_to(SRC).as_posix()
        found.extend(_profile_constructions_in(relative, path.read_text(encoding="utf-8")))
    return found


# ─── C2 helper: 구조적 표면 census ────────────────────────────────────────────────
def _profile_management_surfaces(
    actions: Iterable[str], bridge_methods: Iterable[str], screens: Iterable[str]
) -> set[str]:
    """action/bridge/screen 이름 중 profile/qualification 관리 표면을 돌려준다."""
    tagged = {
        *(f"action:{name}" for name in actions),
        *(f"bridge:{name}" for name in bridge_methods),
        *(f"screen:{name}" for name in screens),
    }
    return {
        surface
        for surface in tagged
        if any(term in surface.lower() for term in _PROFILE_SURFACE_TERMS)
    }


# ─── C3/C4 helpers: frontend/src/domain 전체를 대상으로 ──────────────────────────────
def _domain_semantic_importers(sources: dict[str, str]) -> set[str]:
    """``frontend/src/domain/`` 모듈로 resolve 되는 production frontend import 를 census 한다.

    retained codec 2개는 **importer 로서** 건너뛴다(서로를 codec-internal 로 참조할 수 있다).
    그 외 어떤 모듈이든(새 domain 파일 포함) domain 을 import 하면 위반이다 — canonical/semantic
    권위는 backend/application 단일이라 frontend 는 domain 을 import 하지 않는다.
    """
    domain_modules = {rel for rel in sources if rel.startswith(FRONTEND_DOMAIN_PREFIX)}
    violations: set[str] = set()
    for relative, source in sources.items():
        if relative in RETAINED_CODEC_MODULES:
            continue
        for specifier in _frontend_specifiers(relative, source):
            target = _resolve_frontend_module(relative, specifier, sources)
            if target in domain_modules:
                violations.add(f"{relative}|{specifier}")
    return violations


def _semantic_scan_code(sources: dict[str, str]) -> dict[str, str]:
    """retained codec 2개만 뺀 production frontend 소스의 **code mask**(문자열/주석 제거).

    ``frontend/src/domain/`` 디렉터리 전체가 아니라 **정확히 그 두 codec** 만 제외한다 — 새
    domain 파일은 재계산 스캔 대상으로 남는다.
    """
    return {
        relative: _js_masks(source)[1]
        for relative, source in sources.items()
        if relative not in RETAINED_CODEC_MODULES
    }


def _crypto_and_reauthored(code: dict[str, str]) -> tuple[list[str], list[str]]:
    """code mask 집합에서 digest primitive 사용과 canonical 심볼 재저작을 census 한다."""
    crypto = sorted(rel for rel, masked in code.items() if "crypto.subtle" in masked)
    reauthored = sorted(
        f"{rel}|{symbol}"
        for rel, masked in code.items()
        for symbol in CANONICAL_SEMANTIC_SYMBOLS
        if symbol in masked
    )
    return crypto, reauthored


# ─── C6 helpers: naming-independent durable record 필드 census ─────────────────────────
def _is_frozen_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call) and _short_name(decorator.func) == "dataclass":
            for keyword in decorator.keywords:
                if (
                    keyword.arg == "frozen"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    return True
    return False


def _frozen_dataclass_names(root: Path = SRC / "hwpxfiller") -> frozenset[str]:
    """저장소 전역의 frozen dataclass 이름 집합 — record 판정의 naming-independent 사전."""
    names: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_frozen_dataclass(node):
                names.add(node.name)
    return frozenset(names)


def _sequence_element_name(annotation: ast.expr) -> str | None:
    """``tuple[X, ...]`` / ``Sequence[X]`` 주석에서 element type X 의 short name 을 뽑는다."""
    if not isinstance(annotation, ast.Subscript):
        return None
    base = _short_name(annotation.value)
    slice_node = annotation.slice
    if base == "tuple" and isinstance(slice_node, ast.Tuple) and slice_node.elts:
        return _short_name(slice_node.elts[0])
    if base == "Sequence" and not isinstance(slice_node, ast.Tuple):
        return _short_name(slice_node)
    return None


def _durable_ledger_fields(
    sources: dict[str, str] | None = None, frozen: frozenset[str] | None = None
) -> set[str]:
    """durable aggregate 의 append-only record 필드를 naming-independent 로 census 한다.

    frozen dataclass 의 class-body ``AnnAssign`` 중 annotation 이 ``tuple[X, ...]``/``Sequence[X]``
    이고 X 가 **frozen dataclass**(record)면 durable append-only 사본 필드다 — element type 이름의
    suffix 규약에 의존하지 않는다.
    """
    if frozen is None:
        frozen = _frozen_dataclass_names()
    if sources is None:
        application = SRC / "hwpxfiller" / "application"
        sources = {
            module: (application / module).read_text(encoding="utf-8")
            for module in DURABLE_AGGREGATE_MODULES
        }
    found: set[str] = set()
    for module, source in sources.items():
        tree = ast.parse(source, filename=module)
        for cls in ast.walk(tree):
            if not (isinstance(cls, ast.ClassDef) and _is_frozen_dataclass(cls)):
                continue
            for stmt in cls.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                element = _sequence_element_name(stmt.annotation)
                if element and element in frozen:
                    found.add(f"{module}|{stmt.target.id}|{element}")
    return found


# ─── C1 ──────────────────────────────────────────────────────────────────────────
def test_exactly_one_shipping_qualification_profile() -> None:
    constructions = _profile_constructions()
    assert constructions == [
        "hwpxfiller/external/template_inspection.py|HWPX_QUALIFICATION_PROFILE"
    ], f"shipping Profile 은 정확히 하나여야 한다: {constructions}"

    counts = _call_counts()
    # S5F R2-05a(#740): mutable Profile admission control plane 을 제거했다 — bootstrap-to-ADMITTED·
    # dynamic publication·revoke 가 production·저장소 전역에서 0 이다(immutable Qualification identity 만
    # 남는다). 셋 다 0 이 admission 제어면 부재의 census 증거다.
    for name in REMOVED_ADMISSION_CONTROL_CALLS:
        assert counts[name] == 0, (
            f"{name} 은 R2-05a 에서 제거된 admission 제어면이다(호출 0)"
        )


# ─── C2 ──────────────────────────────────────────────────────────────────────────
def test_no_profile_management_surface() -> None:
    actions = {action for screen in ACTION_REGISTRY.values() for action in screen}
    bridge_methods = {
        name
        for name, value in vars(WebFrontend).items()
        if not name.startswith("_") and callable(value)
    }
    screens = set(ACTION_REGISTRY) | set(NAV_SCREENS)
    offenders = sorted(_profile_management_surfaces(actions, bridge_methods, screens))
    assert not offenders, (
        f"제품 구조 표면에 Profile/qualification 관리 표면이 생겼다: {offenders} — v1 에서 "
        "profile selector/management action·bridge method·screen 은 0 이다. 복수 "
        "runtime/plugin/admin 요구는 별도 설계로 상향한다."
    )


# ─── C3 ──────────────────────────────────────────────────────────────────────────
def test_frontend_does_not_import_domain_semantics() -> None:
    violations = _domain_semantic_importers(_frontend_sources())
    assert not violations, (
        f"production frontend 이 frontend/src/domain semantic 모듈을 import 한다: "
        f"{sorted(violations)} — canonical bytes/digest/currentness 는 backend/application 단일 "
        "권위다. offline/보안상 독립 digest 가 실제로 필요하면 #732/#620 으로 상향한다."
    )


# ─── C4 ──────────────────────────────────────────────────────────────────────────
def test_frontend_recomputes_no_semantics() -> None:
    code = _semantic_scan_code(_frontend_sources())
    # retained codec 2개는 스캔에서 빠지되 그 밖의 domain 파일은 포함돼야 한다(스코프 계약).
    assert all(module not in code for module in RETAINED_CODEC_MODULES)
    crypto, reauthored = _crypto_and_reauthored(code)
    assert not crypto, (
        f"production frontend 이 digest primitive 를 직접 쓴다: {crypto} — currentness/Plan/record "
        "digest 는 backend 판정이다."
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
        f"기존 S4/S5 durable record 필드가 사라졌다: {sorted(removed)} — SG-03 은 제거·migration 이 "
        "아니라 pin 이다. baseline 을 줄이려면 실제 소비자 부재 증거와 함께 별도 슬라이스로 한다."
    )


# ─── negative probes (파일 관례: 게이트가 실제 회피를 잡는지 — 실 게이트 함수를 호출한다) ──────
def test_negative_probe_detects_annotated_and_inline_profile_construction() -> None:
    # 옛 census 는 ``ast.Assign`` 만 봐서 annotated/return/inline 생성이 빠져나갔다. 실 helper 는
    # 호출 노드를 겨눠 모두 센다 — 두 번째 profile 이 있으면 게이트 단언(길이 1)이 RED 다.
    annotated = _profile_constructions_in(
        "probe.py", "second: QualificationProfile = QualificationProfile('a', f)\n"
    )
    assert annotated == ["probe.py|second"]
    inline = _profile_constructions_in(
        "probe.py", "def make():\n    return QualificationProfile('b', g)\n"
    )
    assert inline == ["probe.py|<inline>"]
    call_arg = _profile_constructions_in("probe.py", "register(QualificationProfile('c', h))\n")
    assert call_arg == ["probe.py|<inline>"]

    real = _profile_constructions()
    injected = real + annotated
    assert len(real) == 1 and len(injected) == 2, "annotated 2번째 profile 은 census 를 2로 만든다"


def test_negative_probe_detects_aliased_forbidden_call() -> None:
    """alias 로 숨긴 호출을 census 가 원 이름으로 잡는다 — **C1 이 세는 이름 전건**으로 잰다.

    #805: 이전 판은 이미 삭제된 ``profile_admission_runner`` 를 import 출처로 썼다. 기제 자체는
    유효했지만(alias 해소를 고장 내면 빨강이 난다) 겨누는 표면이 현재가 아니었고, 겨냥이 C1 의
    금지 목록과 **우연히** 겹쳐 있어 한쪽이 바뀌면 조용히 어긋날 수 있었다. 이제 둘 다
    :data:`REMOVED_ADMISSION_CONTROL_CALLS` 하나를 소비하므로 드리프트가 구조적으로 불가능하다.
    """
    for name in REMOVED_ADMISSION_CONTROL_CALLS:
        alias = "hidden_call"
        counts = _call_counts_in(
            f"from {_LIVE_IMPORT_SOURCE_MODULE} import {name} as {alias}\n"
            f"{alias}('work')\n"
        )
        assert counts[name] == 1, f"{name}: alias 를 원 이름으로 해소해야 한다"
        assert counts[alias] == 0, f"{name}: alias 이름으로는 남지 않는다"


def test_negative_probe_import_source_module_exists() -> None:
    """프로브가 fabricate 하는 import 출처가 **실재**한다(#805 수용조건 1).

    삭제된 모듈을 겨누면 프로브는 「현재 코드가 그 표면을 안 쓴다」가 아니라 자기 문자열을 재게
    된다. 출처가 사라지는 순간 이 단언이 빨강으로 알린다.
    """
    assert importlib.util.find_spec(_LIVE_IMPORT_SOURCE_MODULE) is not None, (
        f"{_LIVE_IMPORT_SOURCE_MODULE} 이 사라졌다 — 음성 대조의 겨냥을 실재 모듈로 옮겨라"
    )


def test_negative_probe_detects_profile_management_surface() -> None:
    # action/bridge/screen 중 profile/qualification 이름은 지역화 여부와 무관히 잡힌다.
    assert _profile_management_surfaces(
        {"refresh", "manage_profile"}, set(), set()
    ) == {"action:manage_profile"}
    assert _profile_management_surfaces(
        set(), {"publish_qualification_profile"}, set()
    ) == {"bridge:publish_qualification_profile"}
    assert _profile_management_surfaces(set(), set(), {"qualification"}) == {
        "screen:qualification"
    }


def test_negative_probe_detects_domain_semantic_import() -> None:
    # retained codec import 도, **새 domain 파일** import 도 모두 위반으로 잡힌다.
    sources = {
        "frontend/src/domain/canonical_execution_encoding.ts": "export const x = 1;\n",
        "frontend/src/domain/slot_selection.ts": "export const y = 1;\n",
        "frontend/src/domain/currentness.ts": "export const z = 1;\n",
        "frontend/src/screens/probe.ts": (
            'import { canonicalExecutionDigest } from "../domain/canonical_execution_encoding.ts";\n'
        ),
        "frontend/src/screens/dynamic_probe.ts": (
            'const m = await import("../domain/slot_selection.ts");\n'
        ),
        "frontend/src/screens/new_probe.ts": (
            'import { computeCurrentness } from "../domain/currentness.ts";\n'
        ),
    }
    assert _domain_semantic_importers(sources) == {
        "frontend/src/screens/probe.ts|../domain/canonical_execution_encoding.ts",
        "frontend/src/screens/dynamic_probe.ts|../domain/slot_selection.ts",
        "frontend/src/screens/new_probe.ts|../domain/currentness.ts",
    }


def test_negative_probe_detects_new_domain_recompute() -> None:
    # 새 domain 파일이 digest 를 계산하면 재계산 스캔이 잡는다 — 디렉터리 예외가 아니라 codec
    # 2개만 예외라서 currentness.ts 는 스캔 집합에 든다.
    sources = {
        "frontend/src/domain/canonical_execution_encoding.ts": (
            "await crypto.subtle.digest('SHA-256', b);\n"
        ),
        "frontend/src/domain/currentness.ts": (
            "export async function d(b){ return crypto.subtle.digest('SHA-256', b); }\n"
        ),
    }
    code = _semantic_scan_code(sources)
    assert "frontend/src/domain/currentness.ts" in code, "새 domain 파일은 스캔 대상이다"
    assert "frontend/src/domain/canonical_execution_encoding.ts" not in code, (
        "retained codec 은 스캔에서 제외된다"
    )
    crypto, _reauthored = _crypto_and_reauthored(code)
    assert crypto == ["frontend/src/domain/currentness.ts"]


def test_negative_probe_detects_new_ledger() -> None:
    # record 이름이 suffix 규약(`IdempotencyRecord`/`SealCommandRecord`)을 안 따라도 형상으로 잡힌다.
    frozen = _frozen_dataclass_names() | {"ProcessedCommand"}
    synthetic = {
        "stored_new_command.py": (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class ProcessedCommand:\n"
            "    request_id: str\n"
            "@dataclass(frozen=True)\n"
            "class NewAggregate:\n"
            "    processed: tuple[ProcessedCommand, ...]\n"
            "    label: tuple[str, ...]\n"  # str 은 frozen dataclass 아님 → 무시
        ),
    }
    discovered = _durable_ledger_fields(sources=synthetic, frozen=frozen)
    assert discovered == {"stored_new_command.py|processed|ProcessedCommand"}
    # 실 게이트 계산: baseline 밖이라 RED 이어야 한다.
    assert discovered - LEDGER_BASELINE == discovered
