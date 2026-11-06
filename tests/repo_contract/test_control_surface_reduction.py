"""SG-03(#735) control-surface reduction 정적 게이트 — C1·C2·C6.

v1 제품 표면은 이미 **구성상** 축소돼 있다(census: `docs/architecture.md#architecture-authority`). 이 파일은
그 사실들을 pin 해, 미래 변경이 조용히 표면을 재확장하지 못하게 한다. 순수 static 이라 무표
contract lane 에 산다(실 런타임·브라우저 불요).

각 negative probe 는 **실제 게이트 함수 자체**를 정확한 회피 표본에 대고 호출해 RED 됨을 보인다
(병렬 재구현이 아니다). 회피표본에서 RED 를 못 내는 게이트는 무가치이고, 이 슬라이스의 산출물이
곧 이 게이트들이라 hollow gate 는 결함이다.

- C1 shipping Qualification Profile census == :data:`SHIPPING_QUALIFICATION_PROFILES` (매체마다
  정확히 하나 · dynamic publication 0 · revoke 0).
- C2 제품 Profile/qualification 관리 표면(action·bridge·screen) == 0.
- C6 durable aggregate 의 append-only record 필드가 pinned manifest 밖으로 늘면 RED.

C3/C4 는 Node `frontend_build_graph.test.js`, C5 는 `bridge_contract.test.js`(생성 계약 parity),
C7/C8 은 Rust `slot_configuration_product` 테스트,
C9 는 Rust `canonical_execution_encoding`·`slot_selection` golden 테스트,
`template_qualification` manifest 테스트와 `hwpx_qualification` digest 테스트가 진다.
"""

from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from _web_source import NAV_SCREENS

from hwpxfiller.webapp.action_registry import ACTION_REGISTRY
from hwpxfiller.webapp.app import WebFrontend

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src"
#: shipping Qualification Profile 의 **정확한 census**(개수가 아니라 목록을 pin 한다).
#:
#: C1 이 막는 것은 **profile 을 고르는 제어면**이지 매체가 자기 자격 규칙을 갖는 것이 아니다 —
#: 후자는 매체가 늘 때 정확히 하나씩 늘고, 사용자에게는 어떤 선택지도 되지 않는다(그 금지는
#: C2 가 표면 census 로 따로 진다). S10-02(#859)가 TXT 를 S2/S3 생애주기에 인수하며 목록이
#: 둘이 됐고, 그것은 우회가 아니라 `docs/architecture.md#architecture-authority` 「복수 shipping Profile 이
#: 실제 사용자 흐름에 필수」의 상향 경로(#856 S10 TXT parity)를 탄 결과다. 목록에 없는 생성은
#: 여전히 RED 이므로 「하나만」이 「아무거나」로 풀리지 않는다.
SHIPPING_QUALIFICATION_PROFILES = [
    "hwpxfiller/external/template_inspection.py|HWPX_QUALIFICATION_PROFILE",
    "hwpxfiller/external/text_template_inspection.py|TXT_QUALIFICATION_PROFILE",
]

#: profile/qualification 관리 표면을 겨누는 금지어. 영어 substring 이 아니라 **구조적 표면**
#: (action registry·direct-bridge method·screen/route 상수)의 이름을 census 해 이 토큰을 본다 —
#: 지역화된 라벨(`qualificationPolicy`)이 raw 소스 substring 을 빠져나가는 hollow 를 막는다.
_PROFILE_SURFACE_TERMS = ("profile", "qualification")

#: durable aggregate 모듈 — 여기 있는 frozen dataclass 의 append-only record 필드만 census 한다.
#: (application 전역을 훑지 않는다: in-memory DTO 를 과포획한다.)
DURABLE_AGGREGATE_MODULES = (
    "stored_execution_plan.py",
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
#: `docs/architecture.md#architecture-authority` §신규 ledger allowlist 의 외부효과/중복결과 경계에 해당함을
#: 이슈에서 증명하고, allowlist·baseline 을 함께 넓힌다.
LEDGER_BASELINE = frozenset(
    {
        # S5F R2-04a(#740): stored_execution_plan 의 first-seen seal request ledger 를 제거했다 —
        # seal 은 historical outcome 을 replay 하지 않고 현재 authority 에서 재계산한다(idempotency/
        # replay 소비자 부재). content-addressed Plan history 는 04b 대상으로 남는다.
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
def test_exactly_one_shipping_qualification_profile_per_media() -> None:
    constructions = _profile_constructions()
    assert sorted(constructions) == sorted(SHIPPING_QUALIFICATION_PROFILES), (
        f"shipping Profile census 가 pin 과 다르다: {constructions} — 매체마다 정확히 "
        "하나이고, 새 매체가 아닌 이유로 늘리려면 docs/architecture.md#architecture-authority 상향 조건을 탄다"
    )

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
    # 호출 노드를 겨눠 모두 센다 — pin 목록 **밖의** profile 이 하나라도 있으면 게이트가 RED 다.
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
    pinned = len(SHIPPING_QUALIFICATION_PROFILES)
    assert len(real) == pinned and len(injected) == pinned + 1, (
        "annotated 로 숨긴 추가 profile 도 census 를 한 건 늘린다"
    )


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
